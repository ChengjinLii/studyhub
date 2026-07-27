from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.agentic_platform.execution.factory import DurableRuntimeDependencies, build_durable_agent_runtime_factory
from app.agentic_platform.domain.artifact import ArtifactKind
from app.agentic_platform.domain.transition import AgentTransitionEvent, ModelTurnPurpose, TokenRole, TokenRoleSpan
from app.agentic_platform.persistence.durable_artifact_store import (
    ArtifactIdempotencyPayloadConflictError,
    DurableArtifactStore,
    LocalFilesystemArtifactBlobStore,
)
from app.agentic_platform.persistence.durable_transition_sink import (
    DurableTrajectoryError,
    DurableTransitionSink,
    TransitionIdCollisionError,
)
from app.agentic_platform.persistence.run_lease import RunLease
from app.agentic_platform.runtime.checkpoint import SQLiteCheckpointHandle
from app.agentic_platform.runtime.persistence import SqlAlchemyRuntimePersistence
from app.agentic_platform.skills.registry import build_default_skill_registry
from app.core.config import Settings
from app.models import Base
from app.models.agentic_runtime import AgentArtifactRecord, AgentRunRecord
from tests.agentic_platform.factories import task_state, transition


class _MemoryLock:
    provider_name = "test"

    def __init__(self) -> None:
        self.owners: dict[str, str] = {}

    def acquire(self, session: Session, *, lock_name: str, owner_token: str, ttl_seconds: int) -> bool:
        del session, ttl_seconds
        owner = self.owners.get(lock_name)
        if owner is not None and owner != owner_token:
            return False
        self.owners[lock_name] = owner_token
        return True

    def release(self, session: Session, *, lock_name: str, owner_token: str) -> None:
        del session
        if self.owners.get(lock_name) == owner_token:
            self.owners.pop(lock_name, None)

    def probe(self, *, deep: bool = False) -> dict[str, object]:
        del deep
        return {"status": "ok"}


class _FailingBlobStore:
    def put_bytes(self, *, key: str, content: bytes) -> str:
        del key, content
        raise OSError("simulated external storage failure")


def _artifact_session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'artifacts.sqlite3'}", future=True)
    Base.metadata.create_all(engine, tables=[AgentArtifactRecord.__table__])
    return sessionmaker(bind=engine, expire_on_commit=False, future=True), engine


def _tokenized_transition(*, transition_id: str = "transition-durable-1") -> AgentTransitionEvent:
    event = transition()
    return event.model_copy(
        update={
            "transition_id": transition_id,
            "model_turn_id": f"model-{transition_id}",
            "turn_purpose": ModelTurnPurpose.POLICY,
            "token_ids": [101, 102, 103, 104],
            "token_logprobs": [-0.1, -0.2, -0.3, -0.4],
            "token_role_spans": [
                TokenRoleSpan(role=TokenRole.SYSTEM, start=0, end=1, trainable=False),
                TokenRoleSpan(role=TokenRole.TOOL_OBSERVATION, start=1, end=2, trainable=False),
                TokenRoleSpan(role=TokenRole.ASSISTANT_ACTION, start=2, end=4, trainable=True),
            ],
            "training_eligible": True,
            "quarantine_reason": None,
        }
    )


def test_durable_artifacts_keep_small_json_in_sql_and_large_json_external(tmp_path: Path) -> None:
    session_factory, engine = _artifact_session_factory(tmp_path)
    try:
        store = DurableArtifactStore(
            session_factory,
            blob_store=LocalFilesystemArtifactBlobStore(tmp_path / "artifact-blobs"),
        )
        state = task_state()

        small = asyncio.run(
            store.store_json(
                state,
                artifact_type=ArtifactKind.OTHER,
                artifact_key="small",
                payload={"schema_version": "1.0", "value": "small"},
                summary="small payload",
                idempotency_key="small-payload",
            )
        )
        large = asyncio.run(
            store.store_json(
                state,
                artifact_type=ArtifactKind.OTHER,
                artifact_key="large",
                payload={"schema_version": "1.0", "value": "x" * (65 * 1024)},
                summary="large payload",
                idempotency_key="large-payload",
            )
        )
        duplicate = asyncio.run(
            store.store_json(
                state,
                artifact_type=ArtifactKind.OTHER,
                artifact_key="large",
                payload={"schema_version": "1.0", "value": "x" * (65 * 1024)},
                summary="large payload",
                idempotency_key="large-payload",
            )
        )

        with session_factory() as session:
            records = {record.id: record for record in session.scalars(select(AgentArtifactRecord))}
        assert records[small.artifact_id].content_json is not None
        assert records[small.artifact_id].external_uri is None
        assert records[large.artifact_id].content_json is None
        assert records[large.artifact_id].external_uri == large.uri
        assert records[large.artifact_id].content_size_bytes and records[large.artifact_id].content_size_bytes > 64 * 1024
        assert large.uri.startswith("file:")
        assert Path(large.uri.removeprefix("file://")).is_file()
        assert duplicate.artifact_id == large.artifact_id
        with pytest.raises(ArtifactIdempotencyPayloadConflictError):
            asyncio.run(
                store.store_json(
                    state,
                    artifact_type=ArtifactKind.OTHER,
                    artifact_key="large",
                    payload={"schema_version": "1.0", "value": "different"},
                    summary="different payload",
                    idempotency_key="large-payload",
                )
            )
    finally:
        engine.dispose()


def test_external_artifact_temp_failure_does_not_write_metadata(tmp_path: Path) -> None:
    session_factory, engine = _artifact_session_factory(tmp_path)
    try:
        store = DurableArtifactStore(session_factory, blob_store=_FailingBlobStore())
        with pytest.raises(OSError, match="simulated"):
            asyncio.run(
                store.store_json(
                    task_state(),
                    artifact_type=ArtifactKind.OTHER,
                    artifact_key="large",
                    payload={"value": "x" * (65 * 1024)},
                    summary="large payload",
                    idempotency_key="failed-large",
                )
            )
        with session_factory() as session:
            assert list(session.scalars(select(AgentArtifactRecord))) == []
    finally:
        engine.dispose()


def test_transition_segments_recover_after_transition_and_model_io_crashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = _tokenized_transition()
    model_turn = event.model_turn_event()
    root = tmp_path / "trajectory-root"
    sink = DurableTransitionSink(root)

    # Simulate a worker kill after the immutable Transition segment was fsynced
    # but before its linked ModelIO call began.
    asyncio.run(sink.emit(event))
    with pytest.raises(DurableTrajectoryError, match="trajectory_manifest_missing"):
        sink.load_manifest_for_event(event)

    recovered = DurableTransitionSink(root)
    asyncio.run(recovered.emit(event))  # same Transition retry is idempotent

    import app.agentic_platform.persistence.durable_transition_sink as module

    original_atomic_write = module._atomic_write

    def fail_only_manifest(path: Path, content: bytes) -> None:
        if path.name == "manifest.json":
            raise OSError("simulated manifest crash")
        original_atomic_write(path, content)

    monkeypatch.setattr(module, "_atomic_write", fail_only_manifest)
    with pytest.raises(OSError, match="simulated manifest crash"):
        asyncio.run(recovered.emit_model_turn(model_turn))

    paths = recovered.paths_for_event(event)
    assert (paths.segments_dir / "00000001.transition.json").exists()
    assert (paths.segments_dir / "00000001.model_io.json").exists()
    monkeypatch.setattr(module, "_atomic_write", original_atomic_write)

    final_sink = DurableTransitionSink(root)
    asyncio.run(final_sink.emit_model_turn(model_turn))
    manifest = final_sink.load_manifest_for_event(event)
    assert manifest.transition_count == 1
    assert manifest.model_io_count == 1
    assert manifest.transition_ids == [event.transition_id]
    assert manifest.model_turn_ids == [model_turn.model_turn_id]


def test_transition_id_collision_and_manifest_corruption_fail_closed(tmp_path: Path) -> None:
    event = _tokenized_transition()
    sink = DurableTransitionSink(tmp_path / "trajectory-root")
    asyncio.run(sink.emit(event))
    asyncio.run(sink.emit_model_turn(event.model_turn_event()))

    with pytest.raises(TransitionIdCollisionError):
        asyncio.run(sink.emit(event.model_copy(update={"terminal_reason": "different immutable payload"})))

    paths = sink.paths_for_event(event)
    (paths.segments_dir / "00000001.transition.json").write_text("{not-json}", encoding="utf-8")
    with pytest.raises(DurableTrajectoryError, match="invalid_transition_segment"):
        sink.load_manifest_for_event(event)


def test_run_lease_rejects_second_writer_until_first_releases(tmp_path: Path) -> None:
    session_factory, engine = _artifact_session_factory(tmp_path)
    try:
        provider = _MemoryLock()
        with session_factory() as session:
            first = RunLease(provider, session, run_id="run-lease", owner_token="worker-a", ttl_seconds=60)
            second = RunLease(provider, session, run_id="run-lease", owner_token="worker-b", ttl_seconds=60)
            assert first.acquire() is True
            assert second.acquire() is False
            first.release()
            assert second.acquire() is True
            second.release()
    finally:
        engine.dispose()


def test_production_factory_builds_kernel_with_only_durable_runtime_adapters(tmp_path: Path) -> None:
    session_factory, engine = _artifact_session_factory(tmp_path)
    try:
        settings = Settings(
            agentic_platform_enabled=True,
            agentic_execution_enabled=True,
            agentic_runtime="langgraph",
            agentic_checkpointer="sqlite",
            agentic_durable_storage_enabled=True,
            agentic_artifact_root_dir=str(tmp_path / "agentic-runtime"),
            agentic_model_provider="openai_compatible",
            agentic_model_base_url="https://model.example.invalid/v1",
            agentic_model_api_key="test-key-not-a-secret",
            agentic_model_id="test-agent-model",
            agentic_retriever_version="fixture-material-index-v1",
        )
        factory = build_durable_agent_runtime_factory(
            settings,
            dependencies=DurableRuntimeDependencies(
                session_factory=session_factory,
                skill_registry=build_default_skill_registry(),
                material_repository=object(),
                materials_service=object(),
                pdf_evidence_service=object(),
            ),
        )
        run = AgentRunRecord(
            id="run-production-factory",
            thread_id="thread-production-factory",
            admin_actor_id=3,
            user_id=None,
            trigger_type="admin_api",
            trigger_ref=None,
            runtime_version="langgraph-v1",
            policy_version="policy-v1",
            environment_snapshot_id="snapshot-v1",
            status="running",
        )
        kernel = asyncio.run(factory.build_agent_kernel(run=run, dispatch_payload={}))
        try:
            assert isinstance(kernel.checkpoint_handle, SQLiteCheckpointHandle)
            assert isinstance(kernel.nodes.artifact_store, DurableArtifactStore)
            assert isinstance(kernel.nodes.transition_sink, DurableTransitionSink)
            assert isinstance(kernel.nodes.model_turn_sink, DurableTransitionSink)
            assert isinstance(kernel.persistence, SqlAlchemyRuntimePersistence)
            assert kernel.metadata.retriever_version == "fixture-material-index-v1"
            assert len(kernel.metadata.skill_catalog_hash) == 64
        finally:
            asyncio.run(kernel.close())
    finally:
        engine.dispose()
