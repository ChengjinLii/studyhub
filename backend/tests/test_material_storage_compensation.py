from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest

from app.api.deps import get_materials_service
from app.core.db import session_scope
from app.models.materials import MaterialRecord
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


def _zip_bytes(content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("notes.txt", content)
    return buffer.getvalue()


def _payload(title: str) -> tuple[str, str, str]:
    body = {
        "title": title,
        "description": "storage compensation test",
        "price": 0,
        "school": "电子科技大学",
        "deliveryMethod": "FILE",
        "previewSource": "AUTO",
    }
    return ("payload.json", json.dumps(body, ensure_ascii=False), "application/json")


def test_failed_material_create_removes_new_storage_object(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch,
    tmp_path: Path,
) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(1, 1)
    assert client.get("/api/materials").status_code == 200
    service = get_materials_service()
    original_save = service.material_repo.save_material

    def fail_new_material(session, material):
        if int(material.id) > 104:
            raise RuntimeError("database failure with private details")
        return original_save(session, material)

    monkeypatch.setattr(service.material_repo, "save_material", fail_new_material)
    with pytest.raises(RuntimeError, match="database failure"):
        client.post(
            "/api/materials",
            headers=headers,
            files=[
                ("payload", _payload("创建失败补偿")),
                ("zip", ("compensation.zip", _zip_bytes("new object"), "application/zip")),
            ],
        )

    assert list((tmp_path / "materials").rglob("*compensation.zip")) == []


def test_failed_material_update_keeps_old_object_and_removes_new_object(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch,
    tmp_path: Path,
) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(1, 1)
    create = client.post(
        "/api/materials",
        headers=headers,
        files=[
            ("payload", _payload("更新失败补偿")),
            ("zip", ("old.zip", _zip_bytes("old object"), "application/zip")),
        ],
    )
    assert create.status_code == 200
    material_id = int(create.json()["data"]["id"])
    with session_scope() as session:
        material = session.get(MaterialRecord, material_id)
        assert material is not None
        old_key = str(material.file_storage_key)

    old_path = tmp_path / "materials" / old_key
    assert old_path.exists()
    service = get_materials_service()

    def fail_version(*_args, **_kwargs):
        raise RuntimeError("version write failed")

    monkeypatch.setattr(service.material_repo, "add_version", fail_version)
    with pytest.raises(RuntimeError, match="version write failed"):
        client.put(
            f"/api/materials/{material_id}",
            headers=headers,
            files=[
                ("payload", _payload("更新失败仍保留旧文件")),
                ("zip", ("new.zip", _zip_bytes("new object"), "application/zip")),
            ],
        )

    assert old_path.exists()
    assert list((tmp_path / "materials").rglob("*new.zip")) == []
