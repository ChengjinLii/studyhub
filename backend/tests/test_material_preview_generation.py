from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from PIL import Image, ImageChops
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import JwtTokenCodec
from app.integrations.material_asset_store import MaterialAssetStore
from app.providers.storage import LocalFileStorageProvider
from app.services.material_preview_renderer import watermark_image
from app.services.material_preview_service import MaterialPreviewService
from app.services.material_preview_state import RENDER_VERSION, manifest_payload, public_preview_manifest


def pdf_bytes(pages: int = 4, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=400, height=600)
        content = DecodedStreamObject()
        content.set_data(b"0 0 0 rg 40 350 280 120 re f")
        page[NameObject("/Contents")] = writer._add_object(content)
    if encrypted:
        writer.encrypt("not-public")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def preview_env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'preview.sqlite'}")
    with engine.begin() as connection:
        # Deliberately use the historical schema: no mapped ORM columns required.
        connection.execute(text("""CREATE TABLE materials (
            id INTEGER PRIMARY KEY, uploader_id INTEGER, file_type TEXT, file_key TEXT,
            preview_source TEXT, preview_watermark_enabled INTEGER, preview_manifest TEXT,
            custom_preview_images TEXT, status TEXT, review_status TEXT, deleted_at TEXT
        )"""))
        connection.execute(text("""INSERT INTO materials VALUES
            (1, 8, 'pdf', 'source.pdf', 'AUTO', 1, NULL, '[]', 'VISIBLE', 'APPROVED', NULL)"""))
    settings = SimpleNamespace(private_dir=tmp_path, resolved_material_asset_dir=tmp_path / "assets",
                               material_preview_pages_small=3, material_file_max_size_bytes=50 * 1024**2,
                               material_preview_image_max_size_bytes=5 * 1024**2, material_signed_url_ttl_seconds=300)
    settings.resolved_material_asset_dir.mkdir()
    (settings.resolved_material_asset_dir / "source.pdf").write_bytes(pdf_bytes())
    store = MaterialAssetStore(settings, JwtTokenCodec("preview-test-secret-abcdefghijklmnopqrstuvwxyz"), LocalFileStorageProvider())
    with Session(engine) as session:
        yield MaterialPreviewService(settings, store), session, settings
    engine.dispose()


def test_real_pdf_background_preview_watermark_and_cached_reads(preview_env, monkeypatch):
    service, session, settings = preview_env
    original = (settings.resolved_material_asset_dir / "source.pdf").read_bytes()
    pending = service.get_preview(session, 1, 9, False)
    assert pending["status"] == "processing" and pending["images"] == []
    assert service.run_once(session) == {"done": 1, "failed": 0, "skipped": 0}
    preview = service.get_preview(session, 1, 9, False)
    assert (preview["status"], preview["pageCount"], preview["previewPages"]) == ("done", 4, 3)
    image_url = preview["images"][0]["img"]["src"]
    token = parse_qs(urlparse(image_url).query)["token"][0]
    _, claims = service.resolve_asset(session, 1, 1, token)
    with Image.open(settings.resolved_material_asset_dir / claims["key"]) as image:
        assert image.format == "WEBP" and image.size == (800, 1200)
        assert image.getextrema()[0][0] < 10  # Real PDF rectangle, not a placeholder.
    raw = service.repo.list_rows(session, 1)[0]["preview_manifest"]
    manifest = manifest_payload(raw)
    assert manifest["watermark"] == "StudyHub" and manifest["renderVersion"] == RENDER_VERSION
    assert "source.pdf" not in public_preview_manifest(raw)
    assert (settings.resolved_material_asset_dir / "source.pdf").read_bytes() == original
    monkeypatch.setattr(service, "_generate", lambda *args: pytest.fail("cached reads must not render"))
    assert service.run_once(session)["done"] == 0
    assert service.get_preview(session, 1, 9, False)["status"] == "done"
    session.execute(text("UPDATE materials SET preview_watermark_enabled=0 WHERE id=1"))
    session.commit()
    with pytest.raises(HTTPException) as exc:
        service.resolve_asset(session, 1, 1, token)
    assert exc.value.status_code == 403


def test_watermark_changes_only_copy_and_off_is_unmodified():
    original = Image.new("RGB", (800, 1000), "white")
    enabled = watermark_image(original, True)
    disabled = watermark_image(original, False)
    assert ImageChops.difference(original, enabled).getbbox()
    assert ImageChops.difference(original, disabled).getbbox() is None
    assert original.getextrema() == ((255, 255),) * 3


@pytest.mark.parametrize("invalid", [b"not a PDF", pdf_bytes(encrypted=True)])
def test_invalid_pdf_is_failed_not_placeholder_and_no_original_changes(preview_env, invalid):
    service, session, settings = preview_env
    path = settings.resolved_material_asset_dir / "source.pdf"
    path.write_bytes(invalid)
    assert service.run_once(session)["failed"] == 1
    assert service.get_preview(session, 1, 9, False)["status"] == "failed"
    assert path.read_bytes() == invalid
    assert not list(settings.resolved_material_asset_dir.glob("*/generated-preview/*"))
    assert not list((settings.private_dir / "preview-work").glob("preview-*"))


def test_manual_images_are_rendered_in_background(preview_env):
    service, session, settings = preview_env
    Image.new("RGB", (640, 480), "white").save(settings.resolved_material_asset_dir / "manual.png")
    session.execute(text("UPDATE materials SET preview_source='MANUAL', custom_preview_images='[\"manual.png\"]'"))
    session.commit()
    assert service.get_preview(session, 1, 9, False)["status"] == "processing"
    assert service.run_once(session)["done"] == 1
    preview = service.get_preview(session, 1, 9, False)
    assert preview["pageCount"] == 1 and preview["images"][0]["width"] == 640


def test_failed_worker_cannot_publish_after_source_changed(preview_env, monkeypatch):
    service, session, settings = preview_env
    generate = service._generate

    def change_source(*args):
        result = generate(*args)
        session.execute(text("UPDATE materials SET file_key='replacement.pdf', preview_manifest=NULL WHERE id=1"))
        session.commit()
        return result

    monkeypatch.setattr(service, "_generate", change_source)
    assert service.run_once(session)["failed"] == 1
    assert service.repo.list_rows(session, 1)[0]["preview_manifest"] is None
    assert not list(settings.resolved_material_asset_dir.glob("*/generated-preview/*"))


def test_hidden_materials_security_pending_and_untrusted_remote_images_do_not_publish(preview_env):
    service, session, _ = preview_env
    session.execute(text("UPDATE materials SET status='HIDDEN', review_status='SECURITY_PENDING'"))
    session.commit()
    assert service.run_once(session)["done"] == 0
    with pytest.raises(HTTPException):
        service.get_preview(session, 1, 9, False)
    assert service.get_preview(session, 1, 8, False)["status"] == "processing"
    session.execute(text("UPDATE materials SET status='VISIBLE', review_status='APPROVED', preview_source='MANUAL', "
                         "custom_preview_images='[\"http://169.254.169.254/metadata\"]'"))
    session.commit()
    assert service.run_once(session)["failed"] == 1


def test_claim_compare_and_set_rejects_other_worker(preview_env):
    service, session, _ = preview_env
    row = service.repo.list_rows(session, 1)[0]
    assert service.repo.compare_and_set(session, row, '{"status":"processing"}')
    session.commit()
    assert not service.repo.compare_and_set(session, row, '{"status":"done"}')


def test_experience_illustrations_are_not_preview_jobs(preview_env):
    service, session, _ = preview_env
    session.execute(text("CREATE TABLE material_tags (material_id INTEGER, tag TEXT)"))
    session.execute(text("INSERT INTO material_tags VALUES (1, :tag)"), {"tag": "经验分享"})
    session.commit()
    # Table discovery is intentionally cached like the rest of the repository;
    # clear it to emulate a process starting against this schema.
    from app.repos.material_repo import _TABLE_NAME_CACHE
    _TABLE_NAME_CACHE.clear()
    assert service.run_once(session)["done"] == 0
    assert service.repo.list_rows(session, 1)[0]["preview_manifest"] is None


def test_network_is_blocked_inside_linux_renderer():
    import subprocess
    import sys

    if sys.platform != "linux":
        pytest.skip("Linux seccomp guard")
    code = ("from app.services.material_preview_renderer import _deny_network; import socket; _deny_network(); "
            "\ntry: socket.socket()\nexcept PermissionError: raise SystemExit(0)\nraise SystemExit(1)")
    assert subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], timeout=10).returncode == 0


def test_request_submission_does_not_wait_for_pending_manual_conversion():
    from app.models.materials import MaterialRecord
    from app.services.requests_service import RequestsService
    from app.services.material_preview_state import image_keys

    material = MaterialRecord(preview_source="MANUAL", preview_status="processing", preview_manifest='{"status":"processing"}',
                              manual_preview_keys_json='["first.png", "second.png"]', custom_preview_images_json="[]")
    helper = SimpleNamespace(_loads=image_keys)
    RequestsService._ensure_preview_ready(helper, material)
    material.manual_preview_keys_json = '["first.png"]'
    with pytest.raises(HTTPException):
        RequestsService._ensure_preview_ready(helper, material)
