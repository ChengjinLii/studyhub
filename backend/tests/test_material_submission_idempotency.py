from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import session_scope
from app.models.materials import MaterialRecord, MaterialVersionRecord
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


def _payload(*, title: str, submission_id: str) -> tuple[None, str, str]:
    return (
        None,
        json.dumps(
            {
                "title": title,
                "description": "idempotent material submission",
                "price": 0,
                "school": "电子科技大学",
                "deliveryMethod": "FILE",
                "previewSource": "AUTO",
                "submissionId": submission_id,
            },
            ensure_ascii=False,
        ),
        "application/json",
    )


def _create(client: TestClient, headers: dict[str, str], *, title: str, submission_id: str):
    return client.post(
        "/api/materials",
        headers=headers,
        files=[
            ("payload", _payload(title=title, submission_id=submission_id)),
            ("zip", ("notes.pdf", b"%PDF-1.4\nidempotency\n%%EOF\n", "application/pdf")),
        ],
    )


def test_retried_material_submission_returns_the_original_material(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(1, 1)
    submission_id = "upload_retry_01HZZZZZZZZZZZZZ"

    first = _create(client, headers, title="通信原理复习资料", submission_id=submission_id)
    retry = _create(client, headers, title="通信原理复习资料", submission_id=submission_id)

    assert first.status_code == 200
    assert retry.status_code == 200
    material_id = int(first.json()["data"]["id"])
    assert int(retry.json()["data"]["id"]) == material_id

    with session_scope() as session:
        material_count = session.scalar(
            select(func.count())
            .select_from(MaterialRecord)
            .where(
                MaterialRecord.uploader_id == 1,
                MaterialRecord.submission_key == submission_id,
            )
        )
        version_count = session.scalar(
            select(func.count())
            .select_from(MaterialVersionRecord)
            .where(MaterialVersionRecord.material_id == material_id)
        )

    assert material_count == 1
    assert version_count == 1


def test_submission_id_is_scoped_to_the_uploader(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)
    submission_id = "upload_shared_01HZZZZZZZZZZZZ"

    alice = _create(
        client,
        build_auth_headers(1, 1),
        title="Alice 的资料",
        submission_id=submission_id,
    )
    baishan = _create(
        client,
        build_auth_headers(2, 2),
        title="白山的资料",
        submission_id=submission_id,
    )

    assert alice.status_code == 200
    assert baishan.status_code == 200
    assert alice.json()["data"]["id"] != baishan.json()["data"]["id"]


def test_material_submission_rejects_invalid_submission_id(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)

    response = _create(
        client,
        build_auth_headers(1, 1),
        title="非法投稿标识",
        submission_id="too short",
    )

    assert response.status_code == 400
