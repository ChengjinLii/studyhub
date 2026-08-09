from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.schemas.upload_authorization import UploadFileDescriptorPayload
from app.services.upload_authorization_service import UploadAuthorizationService


def _material(name: str = "notes.pdf", size: int = 128) -> UploadFileDescriptorPayload:
    return UploadFileDescriptorPayload(
        role="MATERIAL",
        name=name,
        sizeBytes=size,
        contentType="application/pdf",
    )


def _service(**overrides: object) -> UploadAuthorizationService:
    values: dict[str, object] = {
        "environment": "test",
        "security_state_backend": "local",
        "upload_authorization_required": True,
        "upload_daily_submission_limit": 2,
        "upload_daily_bytes_limit": 1024,
        "upload_max_concurrent_authorizations": 2,
    }
    values.update(overrides)
    return UploadAuthorizationService(Settings(**values))


def test_upload_ticket_is_bound_and_single_use() -> None:
    service = _service()
    files = [_material()]
    issued = service.authorize(user_id=7, submission_id="upload_ticket_0000001", files=files)

    service.consume(
        token=issued.uploadToken,
        user_id=7,
        submission_id="upload_ticket_0000001",
        files=files,
    )
    with pytest.raises(HTTPException) as replay:
        service.consume(
            token=issued.uploadToken,
            user_id=7,
            submission_id="upload_ticket_0000001",
            files=files,
        )
    assert replay.value.status_code == 409


def test_upload_ticket_rejects_user_submission_and_file_changes() -> None:
    service = _service()
    issued = service.authorize(user_id=7, submission_id="upload_binding_00001", files=[_material()])

    with pytest.raises(HTTPException) as mismatch:
        service.consume(
            token=issued.uploadToken,
            user_id=8,
            submission_id="upload_binding_00001",
            files=[_material()],
        )
    assert mismatch.value.status_code == 400

    with pytest.raises(HTTPException) as changed:
        service.consume(
            token=issued.uploadToken,
            user_id=7,
            submission_id="upload_binding_00001",
            files=[_material(size=129)],
        )
    assert changed.value.status_code == 400


def test_reissuing_same_submission_does_not_double_count_quota() -> None:
    service = _service(upload_daily_submission_limit=1)
    first = service.authorize(user_id=7, submission_id="upload_retry_ticket_01", files=[_material()])
    second = service.authorize(user_id=7, submission_id="upload_retry_ticket_01", files=[_material()])
    assert first.remainingDailySubmissions == 0
    assert second.remainingDailySubmissions == 0

    with pytest.raises(HTTPException) as superseded:
        service.consume(
            token=first.uploadToken,
            user_id=7,
            submission_id="upload_retry_ticket_01",
            files=[_material()],
        )
    assert superseded.value.status_code == 403
    service.consume(
        token=second.uploadToken,
        user_id=7,
        submission_id="upload_retry_ticket_01",
        files=[_material()],
    )


def test_upload_daily_count_and_byte_quotas_are_enforced() -> None:
    count_service = _service(upload_daily_submission_limit=1)
    count_service.authorize(user_id=7, submission_id="upload_count_limit_01", files=[])
    with pytest.raises(HTTPException) as count_limit:
        count_service.authorize(user_id=7, submission_id="upload_count_limit_02", files=[])
    assert count_limit.value.status_code == 429

    byte_service = _service(upload_daily_bytes_limit=100)
    with pytest.raises(HTTPException) as byte_limit:
        byte_service.authorize(user_id=7, submission_id="upload_byte_limit_001", files=[_material(size=101)])
    assert byte_limit.value.status_code == 429


def test_upload_authorization_rejects_unsafe_extensions() -> None:
    service = _service()
    with pytest.raises(HTTPException) as unsafe:
        service.authorize(user_id=7, submission_id="upload_unsafe_file_01", files=[_material(name="payload.exe")])
    assert unsafe.value.status_code == 400


def test_upload_authorization_fails_closed_when_redis_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    service = UploadAuthorizationService(
        Settings(
            environment="production",
            security_state_backend="redis",
            redis_url="redis://cache.invalid",
            upload_authorization_required=True,
        )
    )

    def unavailable():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(service, "_client", unavailable)
    with pytest.raises(HTTPException) as failure:
        service.authorize(user_id=7, submission_id="upload_redis_down_001", files=[_material()])
    assert failure.value.status_code == 503
