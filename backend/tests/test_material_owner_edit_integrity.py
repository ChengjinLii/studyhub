from __future__ import annotations

from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient

from app.core.db import session_scope
from app.models.materials import MaterialRecord
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


ALICE_HEADERS_ARGS = (1, 1)
ADMIN_HEADERS_ARGS = (3, 8)


def _zip_bytes(name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def _payload_part(payload: dict[str, object]) -> tuple[str, str, str]:
    return ("payload.json", json.dumps(payload, ensure_ascii=False), "application/json")


def _material_payload(title: str) -> dict[str, object]:
    return {
        "title": title,
        "description": "owner edit integrity",
        "price": 0,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "gradeType": "STAGE",
        "gradeValue": "大三",
        "generalCourse": False,
        "courseCategory": "MAJOR",
        "tags": "期末速成",
        "deliveryMethod": "FILE",
        "previewWatermarkEnabled": True,
        "previewSource": "AUTO",
        "customPreviewText": None,
        "copyrightOwner": "Alice",
    }


def _create_material(client: TestClient) -> int:
    response = client.post(
        "/api/materials",
        headers=build_auth_headers(*ALICE_HEADERS_ARGS),
        files=[
            ("payload", _payload_part(_material_payload("原始资料"))),
            ("zip", ("notes.zip", _zip_bytes("notes.txt", "hello"), "application/zip")),
        ],
    )
    assert response.status_code == 200
    return int(response.json()["data"]["id"])


def _owner_metadata_edit(client: TestClient, material_id: int, title: str):
    return client.put(
        f"/api/materials/{material_id}",
        headers=build_auth_headers(*ALICE_HEADERS_ARGS),
        files=[("payload", _payload_part(_material_payload(title)))],
    )


def _set_material_state(material_id: int, *, status: str, review_status: str | None) -> None:
    with session_scope() as session:
        material = session.get(MaterialRecord, material_id)
        assert material is not None
        material.status = status
        material.review_status = review_status


def _material_state(material_id: int) -> tuple[str | None, str | None, bool]:
    with session_scope() as session:
        material = session.get(MaterialRecord, material_id)
        assert material is not None
        return material.status, material.review_status, material.deleted_at is not None


def test_owner_edit_cannot_revive_admin_removed_material(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    material_id = _create_material(client)

    removed = client.delete(f"/api/admin/materials/{material_id}", headers=build_auth_headers(*ADMIN_HEADERS_ARGS))
    assert removed.status_code == 200

    response = _owner_metadata_edit(client, material_id, "尝试复活")

    assert response.status_code == 404
    assert _material_state(material_id) == ("REMOVED", "APPROVED", True)
    assert client.get(f"/api/materials/{material_id}").status_code == 404


def test_owner_edit_cannot_revive_moderation_hidden_material(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    material_id = _create_material(client)
    _set_material_state(material_id, status="HIDDEN", review_status="APPROVED")

    response = _owner_metadata_edit(client, material_id, "尝试复活")

    assert response.status_code == 404
    assert _material_state(material_id) == ("HIDDEN", "APPROVED", False)
    assert client.get(f"/api/materials/{material_id}").status_code == 404


def test_owner_metadata_edit_preserves_security_hold(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    material_id = _create_material(client)

    for review_status in ("SECURITY_PENDING", "SECURITY_REJECTED"):
        _set_material_state(material_id, status="HIDDEN", review_status=review_status)

        response = _owner_metadata_edit(client, material_id, f"编辑 {review_status}")

        assert response.status_code == 200
        assert response.json()["data"]["title"] == f"编辑 {review_status}"
        assert _material_state(material_id) == ("HIDDEN", review_status, False)
        assert client.get(f"/api/materials/{material_id}").status_code == 404


def test_owner_metadata_edit_keeps_visible_material_visible(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    material_id = _create_material(client)

    response = _owner_metadata_edit(client, material_id, "正常编辑")

    assert response.status_code == 200
    assert _material_state(material_id) == ("VISIBLE", "APPROVED", False)
    assert client.get(f"/api/materials/{material_id}").status_code == 200
