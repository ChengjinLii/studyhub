from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from app.agentic_platform.application.admin_runs import AdminAgentRunService
from app.agentic_platform.proactive.dispatcher import ProactiveDispatcher
from app.agentic_platform.proactive.jobs import ProactiveAgentWorker
from app.agentic_platform.proactive.outbox import AgentOutboxRepository
from app.agentic_platform.proactive.triggers import ProactiveTriggerService
from app.core.config import Settings
from app.models import Base
from app.models.auth import AuthUser
from app.models.agentic_runtime import (
    AgentArtifactRecord,
    AgentJobRecord,
    AgentJobStatus,
    AgentOutboxRecord,
    AgentOutboxStatus,
    AgentRunRecord,
    AgentThreadRecord,
)
from app.models.materials import MaterialDownloadRecord, MaterialPurchaseRecord, MaterialRecord
from app.repos.agentic_run_repo import AgentRunRepository
from app.repos.auth_repo import AuthRepository
from app.repos.material_repo import MaterialRepository
from app.services.material_pdf_evidence_service import MaterialPageEvidence
from app.services.materials_service import MaterialsService
from app.services.worker_service import WorkerService


MIGRATION_0005_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0005_add_agentic_runtime_tables.py"
MIGRATION_0006_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0006_add_agentic_proactive_outbox.py"
BASE_TIME = datetime(2026, 7, 26, 1, 0, tzinfo=UTC)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    tables = [
        AgentOutboxRecord.__table__,
        AgentThreadRecord.__table__,
        AgentRunRecord.__table__,
        AgentJobRecord.__table__,
        AgentArtifactRecord.__table__,
        MaterialRecord.__table__,
        MaterialDownloadRecord.__table__,
        MaterialPurchaseRecord.__table__,
        AuthUser.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as database_session:
        yield database_session
        database_session.rollback()
    engine.dispose()


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "agentic_platform_enabled": True,
        "agentic_proactive_enabled": True,
        "agentic_shadow_admin_actor_id": 3,
        "agentic_worker_batch_size": 8,
        "agentic_worker_claim_ttl_seconds": 60,
        "agentic_worker_retry_delay_seconds": 0,
        "agentic_worker_max_attempts": 3,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _add_material(session: Session, *, material_id: int = 41) -> MaterialRecord:
    material = MaterialRecord(
        id=material_id,
        title="概率论真题",
        is_free=True,
        file_type="pdf",
        file_storage_key=f"materials/{material_id}.pdf",
    )
    session.add(material)
    session.commit()
    return material


class _EvidenceService:
    def __init__(self, *, failures_before_success: int = 0) -> None:
        self.failures_before_success = failures_before_success
        self.calls = 0

    def collect_for_material(self, material: MaterialRecord, query: str, **_: object) -> list[MaterialPageEvidence]:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError("temporary source fault")
        return [
            MaterialPageEvidence(
                material_id=material.id,
                title=material.title,
                page=7,
                text=f"{query}：第 1 题要求计算期望值。",
                score=88,
                source_type="exercise",
            )
        ]


def _enqueue_download(session: Session, settings: Settings, *, material_id: int = 41):
    result = ProactiveTriggerService(settings).enqueue_material_downloaded(
        session,
        material_id=material_id,
        material_title="概率论真题",
        downloaded_by_user_id=9,
    )
    assert result is not None
    session.commit()
    return result


def _material_jobs(session: Session) -> list[AgentJobRecord]:
    return list(
        session.scalars(
            select(AgentJobRecord)
            .where(AgentJobRecord.job_type == "proactive.material_analysis")
            .order_by(AgentJobRecord.id.asc())
        )
    )


def test_duplicate_material_event_dispatches_once_and_artifact_is_admin_visible(session: Session) -> None:
    settings = _settings()
    _add_material(session)
    first, first_created = _enqueue_download(session, settings)
    duplicate, duplicate_created = _enqueue_download(session, settings)

    assert first_created is True
    assert duplicate_created is False
    assert duplicate.id == first.id

    result = ProactiveAgentWorker(settings, pdf_evidence_service=_EvidenceService()).run_once(
        session,
        worker_id="worker-duplicate",
        now=BASE_TIME,
    )

    assert result["outboxDispatched"] == 2  # material event plus one daily due event
    assert result["jobsCompleted"] == 2
    assert [(item.status, item.attempts) for item in session.scalars(select(AgentOutboxRecord))] == [
        (AgentOutboxStatus.DISPATCHED.value, 1),
        (AgentOutboxStatus.DISPATCHED.value, 1),
    ]
    jobs = _material_jobs(session)
    assert len(jobs) == 1
    assert jobs[0].status == AgentJobStatus.COMPLETED.value
    assert jobs[0].attempts == 1

    artifacts = AdminAgentRunService(settings).list_artifacts(
        session,
        admin_actor_id=3,
        artifact_type="material_analysis",
    )
    assert len(artifacts["items"]) == 1
    assert artifacts["items"][0]["preview"]["material_id"] == 41
    assert artifacts["items"][0]["preview"]["artifact_type"] == "material_analysis"
    assert session.scalar(select(AgentArtifactRecord).where(AgentArtifactRecord.artifact_type == "daily_brief")) is not None


def test_worker_restart_reclaims_stale_proactive_job(session: Session) -> None:
    settings = _settings(agentic_worker_retry_delay_seconds=1)
    _add_material(session)
    event, _created = _enqueue_download(session, settings)
    outbox = AgentOutboxRepository()
    dispatcher = ProactiveDispatcher(settings, outbox_repository=outbox)
    runs = AgentRunRepository()

    claimed_event = outbox.claim_next(
        session,
        claimed_by="worker-before-restart",
        claim_ttl_seconds=settings.agentic_worker_claim_ttl_seconds,
        now=BASE_TIME,
    )
    assert claimed_event is not None and claimed_event.id == event.id
    session.commit()
    dispatched = dispatcher.dispatch(session, event=claimed_event)
    outbox.mark_dispatched(session, event_id=claimed_event.id, claimed_by="worker-before-restart")
    session.commit()

    claimed_job = runs.claim_next_job(
        session,
        job_types=("proactive.material_analysis",),
        claimed_by="worker-before-restart",
        claim_ttl_seconds=settings.agentic_worker_claim_ttl_seconds,
        now=BASE_TIME,
    )
    assert claimed_job is not None and claimed_job.id == dispatched.job_id
    session.commit()

    result = ProactiveAgentWorker(settings, pdf_evidence_service=_EvidenceService()).run_once(
        session,
        worker_id="worker-after-restart",
        now=BASE_TIME + timedelta(seconds=settings.agentic_worker_claim_ttl_seconds + 1),
    )

    job = session.get(AgentJobRecord, dispatched.job_id)
    assert result["jobsCompleted"] >= 1
    assert job is not None
    assert job.status == AgentJobStatus.COMPLETED.value
    assert job.attempts == 2
    assert session.scalar(select(AgentArtifactRecord).where(AgentArtifactRecord.artifact_type == "material_analysis")) is not None


def test_failed_proactive_job_retries_without_losing_the_run(session: Session) -> None:
    settings = _settings(agentic_worker_retry_delay_seconds=0, agentic_worker_max_attempts=3)
    _add_material(session)
    _enqueue_download(session, settings)
    evidence = _EvidenceService(failures_before_success=1)
    worker = ProactiveAgentWorker(settings, pdf_evidence_service=evidence)

    first = worker.run_once(session, worker_id="worker-retry-1", now=BASE_TIME)
    job = _material_jobs(session)[0]
    assert first["jobsRetried"] == 1
    assert job.status == AgentJobStatus.PENDING.value
    assert job.attempts == 1
    assert job.error_code == "pdf_evidence_unavailable"

    second = worker.run_once(session, worker_id="worker-retry-2", now=BASE_TIME + timedelta(seconds=1))
    refreshed = session.get(AgentJobRecord, job.id)
    run = session.get(AgentRunRecord, job.run_id)
    assert second["jobsCompleted"] >= 1
    assert refreshed is not None and refreshed.status == AgentJobStatus.COMPLETED.value
    assert refreshed.attempts == 2
    assert run is not None and run.status == "completed"
    assert evidence.calls == 2


def test_shadow_mode_is_inert_without_explicit_flags(session: Session) -> None:
    _add_material(session)
    settings = Settings()
    result = ProactiveTriggerService(settings).enqueue_material_downloaded(
        session,
        material_id=41,
        material_title="概率论真题",
        downloaded_by_user_id=9,
    )

    assert result is None
    assert list(session.scalars(select(AgentOutboxRecord))) == []


def test_proactive_configuration_requires_explicit_platform_and_admin_actor() -> None:
    with pytest.raises(RuntimeError, match="PROACTIVE_ENABLED"):
        Settings(agentic_proactive_enabled=True, agentic_shadow_admin_actor_id=3).validate_runtime_configuration()
    with pytest.raises(RuntimeError, match="SHADOW_ADMIN_ACTOR_ID"):
        Settings(agentic_platform_enabled=True, agentic_proactive_enabled=True).validate_runtime_configuration()


def test_material_download_writes_one_shadow_outbox_event_in_its_commit(session: Session) -> None:
    class ReadRepository:
        def load_seed(self):
            return {}

    class AssetStore:
        def build_download_url(self, **_: object):
            return "https://download.invalid/material.pdf", "2026-07-26T02:00:00+00:00"

    settings = _settings()
    session.add(
        AuthUser(
            id=9,
            username="reader",
            nickname="reader",
            role_mask=1,
            verified=True,
            free_download_quota=10,
        )
    )
    _add_material(session)
    service = MaterialsService(
        settings,
        ReadRepository(),
        AuthRepository(),
        MaterialRepository(),
        AssetStore(),
        ProactiveTriggerService(settings),
    )

    service.generate_download(session, 41, user_id=9, role_mask=1)
    service.generate_download(session, 41, user_id=9, role_mask=1)

    outbox_events = list(session.scalars(select(AgentOutboxRecord)))
    assert len(outbox_events) == 1
    assert outbox_events[0].event_type == "material_downloaded"
    assert outbox_events[0].status == AgentOutboxStatus.PENDING.value
    assert len(list(session.scalars(select(MaterialDownloadRecord)))) == 1


def test_old_worker_all_job_does_not_execute_agentic_worker() -> None:
    class Lock:
        provider_name = "test"

        def acquire(self, session, *, lock_name, owner_token, ttl_seconds):
            return True

        def release(self, session, *, lock_name, owner_token):
            return None

        def probe(self, *, deep=False):
            return {"status": "ok"}

    class Payout:
        def generate_pending_settlements(self, session):
            return 2

        def refresh_pending_transfers(self, session):
            return 3

    class Requests:
        def run_request_maintenance(self, session):
            return {"maintained": 1}

        def run_scheduled_refunds(self, session):
            return {"refunded": 1}

    class NeverRunAgentic:
        def run_once(self, *args, **kwargs):
            raise AssertionError("legacy all worker must not invoke agentic Shadow Mode")

        def is_enabled(self):
            return True

    worker = WorkerService(
        Settings(),
        Payout(),
        Requests(),
        Lock(),
        NeverRunAgentic(),
    )
    result = worker.run_named_job(SimpleNamespace(), "all", owner_token="legacy-worker")

    assert set(result) == {"settlement", "requestMaintenance", "requestRefund", "payoutTransfer"}


def _load_migration(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_proactive_outbox_migration_up_and_down_on_sqlite(monkeypatch) -> None:
    migration_0005 = _load_migration(MIGRATION_0005_PATH, "studyhub_alembic_0005_for_0006")
    migration_0006 = _load_migration(MIGRATION_0006_PATH, "studyhub_alembic_0006")
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        monkeypatch.setattr(migration_0005, "op", SimpleNamespace(get_bind=lambda: connection))
        monkeypatch.setattr(migration_0006, "op", SimpleNamespace(get_bind=lambda: connection))

        migration_0005.upgrade()
        migration_0006.upgrade()
        assert "agent_outbox_events" in inspect(connection).get_table_names()
        migration_0006.downgrade()
        assert "agent_outbox_events" not in inspect(connection).get_table_names()
    engine.dispose()


def test_proactive_outbox_metadata_uses_portable_text_payloads() -> None:
    ddl = str(CreateTable(AgentOutboxRecord.__table__).compile(dialect=mysql.dialect()))

    assert "agent_outbox_events" in ddl
    assert "TEXT" in ddl.upper()
    assert " JSON" not in ddl.upper()
