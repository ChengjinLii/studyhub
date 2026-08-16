from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.materials import MaterialRecord, MaterialSecurityScanRecord
from app.repos.material_repo import MaterialRepository
from app.services.material_security_service import LIGHTWEIGHT_SCANNER_VERSION, MaterialSecurityService


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


def _security_service(tmp_path: Path) -> MaterialSecurityService:
    return MaterialSecurityService(
        Settings(environment="local-dev", private_dir_path=str(tmp_path)),
        MaterialRepository(),
        object(),  # type: ignore[arg-type]
    )


def test_lightweight_scan_accepts_plain_pdf_without_clamav(tmp_path: Path) -> None:
    path = tmp_path / "plain.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)

    result = _security_service(tmp_path)._lightweight_scan(path)

    assert result is not None
    assert result.status == "CLEAN"
    assert result.version == LIGHTWEIGHT_SCANNER_VERSION


def test_lightweight_scan_escalates_active_pdf_to_clamav(tmp_path: Path) -> None:
    path = tmp_path / "active.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_js("app.alert('test')")
    with path.open("wb") as handle:
        writer.write(handle)

    assert _security_service(tmp_path)._lightweight_scan(path) is None


def test_lightweight_scan_accepts_valid_image(tmp_path: Path) -> None:
    path = tmp_path / "preview.png"
    Image.new("RGB", (32, 32), "white").save(path)

    result = _security_service(tmp_path)._lightweight_scan(path)

    assert result is not None
    assert result.status == "CLEAN"
    assert result.version == LIGHTWEIGHT_SCANNER_VERSION


def test_lightweight_scan_sends_office_and_archives_to_clamav(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_bytes(b"PK\x03\x04")

    assert _security_service(tmp_path)._lightweight_scan(path) is None
