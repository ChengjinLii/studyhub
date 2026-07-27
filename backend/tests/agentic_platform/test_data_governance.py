from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.agentic_platform.domain.data_policy import (
    ExportTarget,
    LicenseClass,
    TrainingDataPolicy,
    aggregate_data_policies,
)
from app.agentic_platform.domain.state_abstract import state_group_features, state_group_key_v2
from app.agentic_platform.persistence.durable_artifact_store import DurableArtifactStore, LocalFilesystemArtifactBlobStore
from app.agentic_platform.persistence.durable_transition_sink import DurableTransitionSink
from app.agentic_platform.runtime.persistence import SqlAlchemyRuntimePersistence
from app.agentic_platform.simulation.trajectory import ModelIORecord, TransitionJsonlSink, trajectory_id_for_event
from app.models import Base
from app.models.agentic_runtime import AgentArtifactRecord
from ml.agentic_platform.collection.pilot import PilotScenario, PilotScenarioManifest, run_pilot
from ml.agentic_platform.collection.validation import validate_pilot_dataset
from ml.agentic_platform.data_governance import DatasetExportDenied, DatasetExportGuard
from tests.agentic_platform.test_trajectory_export import _tokenized_transition


MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0007_add_agentic_data_governance.py"


def _trainable_event(*, scenario_id: str = "policy-scenario"):
    return _tokenized_transition(
        thread_id=f"thread-{scenario_id}",
        run_id=f"run-{scenario_id}",
        transition_id=f"transition-{scenario_id}",
    ).model_copy(
        update={
            "training_eligible": True,
            "data_policy": TrainingDataPolicy.synthetic_trainable(),
        }
    )


async def pilot_runner(*, scenario: dict[str, object], provider: str, trajectory_root: str, output_dir: str) -> dict[str, object]:
    del provider, output_dir
    scenario_id = str(scenario["scenario_id"])
    event = _trainable_event(scenario_id=scenario_id)
    sink = DurableTransitionSink(trajectory_root)
    await sink.emit(event)
    await sink.emit_model_turn(event.model_turn_event())
    return {
        "status": "completed",
        "trajectory_id": trajectory_id_for_event(event),
        "turn_count": 1,
        "tool_count": 0,
        "replay_consistent": True,
        "citation_valid": True,
    }


def test_policy_export_guard_fails_closed_and_preserves_nontrainable_observations() -> None:
    record = ModelIORecord.from_transition(_trainable_event()).model_dump(mode="json")
    guard = DatasetExportGuard()

    assert guard.authorize_record(record, target=ExportTarget.TRAIN).license_class == LicenseClass.SYNTHETIC_TRAINABLE
    for policy, target, reason in (
        (TrainingDataPolicy.internal_eval_only(), ExportTarget.TRAIN, "training_not_allowed"),
        (TrainingDataPolicy.restricted_no_export(), ExportTarget.EVAL, "restricted_no_export"),
        (TrainingDataPolicy.personal_no_training(), ExportTarget.TRAIN, "personal_no_training"),
    ):
        with pytest.raises(DatasetExportDenied, match=reason):
            guard.authorize_record(record | {"data_policy": policy.model_dump(mode="json")}, target=target)

    invalid_observation = record | {
        "token_role_spans": [
            {"role": "tool_observation", "start": 0, "end": 1, "trainable": True},
            {"role": "assistant_action", "start": 1, "end": 5, "trainable": True},
        ]
    }
    with pytest.raises(DatasetExportDenied, match="observation_tokens_must_not_be_trainable"):
        guard.authorize_record(invalid_observation, target=ExportTarget.TRAIN)

    mixed_retention = aggregate_data_policies(
        [
            TrainingDataPolicy.synthetic_trainable(retention_policy="retention-a"),
            TrainingDataPolicy.synthetic_trainable(retention_policy="retention-b"),
        ]
    )
    assert mixed_retention.license_class == LicenseClass.INTERNAL_EVAL_ONLY
    assert mixed_retention.retention_policy == "mixed_trainable_sources_require_review"


def test_artifact_policy_is_persisted_with_a_safe_default_and_explicit_override(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'artifact-policy.sqlite3'}", future=True)
    Base.metadata.create_all(engine, tables=[AgentArtifactRecord.__table__])
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        store = DurableArtifactStore(session_factory, blob_store=LocalFilesystemArtifactBlobStore(tmp_path / "blobs"))
        from tests.agentic_platform.factories import task_state

        reference = asyncio.run(
            store.store_json(
                task_state(),
                artifact_type="pilot_fixture",
                artifact_key="training-safe",
                payload={"schema_version": "1.0", "value": "fixture"},
                summary="synthetic fixture",
                idempotency_key="policy-fixture",
                data_policy=TrainingDataPolicy.synthetic_trainable(),
            )
        )
        with session_factory() as session:
            record = session.scalar(select(AgentArtifactRecord).where(AgentArtifactRecord.id == reference.artifact_id))
        assert record is not None
        assert record.training_allowed is True
        assert record.license_class == LicenseClass.SYNTHETIC_TRAINABLE.value
        assert record.retention_policy == "synthetic_training_standard"
    finally:
        engine.dispose()


def test_state_group_v2_ignores_goal_and_plan_step_identifiers_and_is_shared_by_sql_persistence() -> None:
    from tests.agentic_platform.factories import task_state

    first = task_state()
    second_plan = first.plan.model_copy(
        update={
            "plan_id": "another-plan-id",
            "steps": [
                first.plan.steps[0].model_copy(update={"step_id": "different-step-a"}),
                first.plan.steps[1].model_copy(update={"step_id": "different-step-b"}),
            ],
        }
    )
    second = first.model_copy(
        update={
            "goal": first.goal.model_copy(update={"goal_id": "different-goal-id"}),
            "plan": second_plan,
        }
    )

    assert state_group_features(first) == state_group_features(second)
    assert state_group_key_v2(first) == state_group_key_v2(second)
    assert SqlAlchemyRuntimePersistence._state_group_key_v2(first) == state_group_key_v2(first)


def test_manifests_carry_the_aggregate_data_policy(tmp_path: Path) -> None:
    event = _trainable_event()
    jsonl_sink = TransitionJsonlSink(tmp_path / "jsonl")
    asyncio.run(jsonl_sink.emit(event))
    manifest = jsonl_sink.manifest_for_event(event)
    assert manifest is not None
    assert manifest.data_policy.license_class == LicenseClass.SYNTHETIC_TRAINABLE

    durable_sink = DurableTransitionSink(tmp_path / "durable")
    asyncio.run(durable_sink.emit(event))
    asyncio.run(durable_sink.emit_model_turn(event.model_turn_event()))
    durable_manifest = durable_sink.load_manifest_for_event(event)
    assert durable_manifest.data_policy.license_class == LicenseClass.SYNTHETIC_TRAINABLE


def test_manifest_driven_pilot_and_gate_validate_a_real_immutable_trajectory(tmp_path: Path) -> None:
    manifest = PilotScenarioManifest(
        trajectory_root=str(tmp_path / "trajectories"),
        runner=f"{__name__}:pilot_runner",
        scenarios=[
            PilotScenario(
                scenario_id="one",
                data_policy=TrainingDataPolicy.synthetic_trainable(),
            )
        ],
    )
    report = asyncio.run(
        run_pilot(
            manifest,
            count=1,
            concurrency=1,
            provider="fixture-provider",
            output_dir=tmp_path / "pilot-output",
        )
    )

    gate = validate_pilot_dataset(
        report,
        target=ExportTarget.TRAIN,
        scenario_manifest=manifest,
        required_count=1,
        ci_passed=True,
        mysql_migration_verified=True,
    )
    assert gate.gate_passed is True
    assert gate.token_coverage == {"covered": 1, "total": 1}
    assert gate.manifest_verification == {"verified": 1, "failed": 0}


def test_data_governance_migration_is_explicit_and_additive(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("studyhub_alembic_0007", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Inspector:
        def get_table_names(self) -> list[str]:
            return ["agent_artifacts", "agent_steps"]

        def get_columns(self, table_name: str) -> list[dict[str, str]]:
            del table_name
            return [{"name": "id"}]

    calls: list[tuple[str, str]] = []
    fake_op = SimpleNamespace(
        get_bind=lambda: object(),
        add_column=lambda table, column: calls.append((table, column.name)),
    )
    monkeypatch.setattr(module, "op", fake_op)
    monkeypatch.setattr(module.sa, "inspect", lambda bind: Inspector())

    module.upgrade()

    assert {column for table, column in calls if table == "agent_artifacts"} == {
        "training_allowed",
        "sensitivity",
        "license_class",
        "source_scope",
        "contains_personal_data",
        "anonymization_version",
        "retention_policy",
    }
    assert ("agent_steps", "state_group_key_v2") in calls
    assert "app.models" not in MIGRATION_PATH.read_text(encoding="utf-8")
