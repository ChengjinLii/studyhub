from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

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


def test_submission_reservation_satisfies_production_required_fields(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    observed: list[MaterialRecord] = []

    def inspect_pending_materials(session: Session, _flush_context, _instances) -> None:
        for entity in session.new:
            if not isinstance(entity, MaterialRecord) or not entity.submission_key:
                continue
            assert entity.school == "电子科技大学"
            assert entity.file_type == "pdf"
            assert entity.course_category == "MAJOR"
            assert entity.grade_type == "STAGE"
            assert entity.review_status == "APPROVED"
            observed.append(entity)

    event.listen(Session, "before_flush", inspect_pending_materials)
    try:
        response = _create(
            client,
            build_auth_headers(1, 1),
            title="生产字段约束回归",
            submission_id="upload_required_01HZZZZZZZZZ",
        )
    finally:
        event.remove(Session, "before_flush", inspect_pending_materials)

    assert response.status_code == 200
    assert len(observed) == 1


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


def test_material_submission_accepts_only_matching_one_time_upload_ticket(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    submission_id = "upload_authorized_01HZZZZZZZZ"
    content = b"%PDF-1.4\nauthorized\n%%EOF\n"
    headers = build_auth_headers(1, 1)
    authorization = client.post(
        "/api/material-upload-authorizations",
        headers=headers,
        json={
            "submissionId": submission_id,
            "files": [
                {
                    "role": "MATERIAL",
                    "name": "notes.pdf",
                    "sizeBytes": len(content),
                    "contentType": "application/pdf",
                }
            ],
        },
    )
    assert authorization.status_code == 200, authorization.text
    upload_token = authorization.json()["data"]["uploadToken"]
    authorized_headers = {**headers, "X-StudyHub-Upload-Token": upload_token}

    first = client.post(
        "/api/materials",
        headers=authorized_headers,
        files=[
            ("payload", _payload(title="授权投稿", submission_id=submission_id)),
            ("zip", ("notes.pdf", content, "application/pdf")),
        ],
    )
    assert first.status_code == 200, first.text

    replay = client.post(
        "/api/materials",
        headers=authorized_headers,
        files=[
            ("payload", _payload(title="授权投稿", submission_id=submission_id)),
            ("zip", ("notes.pdf", content, "application/pdf")),
        ],
    )
    assert replay.status_code == 409
