from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.materials import MaterialRecord, MaterialSecurityScanRecord
from app.repos.material_repo import MaterialRepository


def test_material_security_scan_requires_explicit_enablement() -> None:
    assert Settings(environment="production").resolved_material_security_scan_enabled is False
    assert Settings(environment="local-dev").resolved_material_security_scan_enabled is False
    assert Settings(environment="production", material_security_scan_enabled=True).resolved_material_security_scan_enabled is True


def test_security_scan_repository_recovers_abandoned_claim(tmp_path: Path) -> None:
    del tmp_path
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    MaterialRecord.__table__.create(bind=engine)
    MaterialSecurityScanRecord.__table__.create(bind=engine)
    repo = MaterialRepository()
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(
            MaterialRecord(
                id=1,
                title="pending material",
                status="HIDDEN",
                review_status="SECURITY_PENDING",
            )
        )
        repo.save_security_scan(
            session,
            MaterialSecurityScanRecord(
                material_id=1,
                object_key="1/file/test.pdf",
                status="SCANNING",
                claimed_at=None,
            ),
        )
        session.commit()
        ready = repo.list_ready_security_scans(session, now, stale_before=now, limit=2)
    assert [item.material_id for item in ready] == [1]
