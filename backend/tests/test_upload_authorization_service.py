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


def test_bulk_limits_and_normal_material_limit() -> None:
    service = _service()
    files = [_material(name=f"notes-{index}.pdf", size=5 * 1024 * 1024) for index in range(20)]
    assert service.validate_descriptors(files, bulk=True) == files
    assert service.validate_descriptors([_material(size=50 * 1024 * 1024)], bulk=True)
    invalid = [
        files + [_material()],
        [_material(size=50 * 1024 * 1024 + 1)],
        files[:-1] + [_material(size=5 * 1024 * 1024 + 1)],
        [_material(name="unsafe.exe")],
        [UploadFileDescriptorPayload(role="PREVIEW", name="image.png", sizeBytes=1, contentType="image/png")],
    ]
    for descriptors in invalid:
        with pytest.raises(HTTPException) as failure:
            service.validate_descriptors(descriptors, bulk=True)
        assert failure.value.status_code == 400
    with pytest.raises(HTTPException) as normal:
        service.validate_descriptors([_material(), _material()])
    assert normal.value.status_code == 400


def test_batch_reservation_consumes_once_and_shares_normal_quota() -> None:
    service = _service(upload_max_concurrent_authorizations=1)
    files = [_material(), _material(name="second.pdf")]
    remaining = service.reserve_batch(user_id=7, submission_id="batch_1", files=files)
    assert remaining == {"remainingDailySubmissions": 1, "remainingDailyBytes": 768}
    assert service.reserve_batch(user_id=7, submission_id="batch_1", files=files) == remaining
    assert all(ticket.used for ticket in service._local_tickets.values())
    assert service._local_reservations[service._reservation_key(7, "bulk-batch_1")].active_ticket_key is None
    # The ordinary submission ID does not collide with the bulk reservation.
    normal = service.authorize(user_id=7, submission_id="batch_1", files=[_material()])
    assert normal.remainingDailySubmissions == 0
    assert normal.remainingDailyBytes == 640
    service.consume(token=normal.uploadToken, user_id=7, submission_id="batch_1", files=[_material()])
    with pytest.raises(HTTPException) as exhausted:
        service.reserve_batch(user_id=7, submission_id="batch_2", files=[])
    assert exhausted.value.status_code == 429
    assert service.reserve_batch(user_id=8, submission_id="batch_1", files=files) == remaining


def test_normal_and_bulk_share_byte_limit_without_charging_failed_reservation() -> None:
    service = _service(upload_daily_bytes_limit=300)
    normal = service.authorize(user_id=7, submission_id="normal", files=[_material(size=100)])
    with pytest.raises(HTTPException) as exhausted:
        service.reserve_batch(user_id=7, submission_id="batch", files=[_material(size=201)])
    assert exhausted.value.status_code == 429
    remaining = service.reserve_batch(user_id=7, submission_id="batch", files=[_material(size=200)])
    assert remaining == {"remainingDailySubmissions": 0, "remainingDailyBytes": 0}
    service.consume(token=normal.uploadToken, user_id=7, submission_id="normal", files=[_material(size=100)])


def test_batch_retry_rejects_changed_descriptors() -> None:
    service = _service()
    service.reserve_batch(user_id=7, submission_id="batch", files=[_material()])
    with pytest.raises(HTTPException) as changed:
        service.reserve_batch(user_id=7, submission_id="batch", files=[_material(size=129)])
    assert changed.value.status_code == 409


def test_batch_retry_after_ticket_expiry_and_daily_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime
    import app.services.upload_authorization_service as module

    now = datetime(2026, 9, 20, 12, tzinfo=UTC).timestamp()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(now, tz=tz)

    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(module, "time", lambda: now)
    service = _service(upload_daily_submission_limit=1)
    files = [_material()]
    first = service.reserve_batch(user_id=7, submission_id="batch", files=files)
    now += 3600
    assert service.reserve_batch(user_id=7, submission_id="batch", files=files) == first
    now += 86400
    # A retry from yesterday does not use today's quota while its reservation survives.
    assert service.reserve_batch(user_id=7, submission_id="batch", files=files) == {
        "remainingDailySubmissions": 1, "remainingDailyBytes": 1024,
    }
    assert service.reserve_batch(user_id=7, submission_id="new_batch", files=files) == first


def test_bulk_authorize_consume_and_replay() -> None:
    service = _service()
    files = [_material(), _material(name="second.pdf")]
    issued = service.authorize(user_id=7, submission_id="bulk-batch", files=files, bulk=True)
    service.consume(token=issued.uploadToken, user_id=7, submission_id="bulk-batch", files=files, bulk=True)
    with pytest.raises(HTTPException) as replay:
        service.consume(token=issued.uploadToken, user_id=7, submission_id="bulk-batch", files=files, bulk=True)
    assert replay.value.status_code == 409


def test_batch_redis_shared_quota_retry_and_day_rollover(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    import subprocess
    import time

    import redis

    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for isolated Lua integration coverage")
    socket = str(tmp_path / "redis.sock")
    process = subprocess.Popen(
        [executable, "--port", "0", "--unixsocket", socket, "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = redis.Redis(unix_socket_path=socket)
    try:
        for _ in range(100):
            try:
                if client.ping():
                    break
            except redis.ConnectionError:
                time.sleep(0.02)
        else:
            pytest.fail("isolated Redis did not start")
        service = _service(security_state_backend="redis", upload_max_concurrent_authorizations=1)
        service._redis_client = client
        files = [_material(), _material(name="second.pdf")]
        first = service.reserve_batch(user_id=7, submission_id="batch", files=files)
        assert first == {"remainingDailySubmissions": 1, "remainingDailyBytes": 768}
        assert service.reserve_batch(user_id=7, submission_id="batch", files=files) == first
        assert client.zcard(service._active_key(7)) == 0
        with pytest.raises(HTTPException) as changed:
            service.reserve_batch(user_id=7, submission_id="batch", files=[_material(size=129)])
        assert changed.value.status_code == 409
        with pytest.raises(HTTPException) as bytes_exhausted:
            service.authorize(user_id=7, submission_id="too_large", files=[_material(size=769)])
        assert bytes_exhausted.value.status_code == 429
        normal = service.authorize(user_id=7, submission_id="normal", files=[_material()])
        assert normal.remainingDailySubmissions == 0 and normal.remainingDailyBytes == 640
        service.consume(token=normal.uploadToken, user_id=7, submission_id="normal", files=[_material()])
        with pytest.raises(HTTPException) as exhausted:
            service.reserve_batch(user_id=7, submission_id="batch_2", files=[])
        assert exhausted.value.status_code == 429
        original_quota_key = service._quota_key
        monkeypatch.setattr(service, "_quota_key", lambda user_id: original_quota_key(user_id) + ":next-day")
        assert service.reserve_batch(user_id=7, submission_id="batch", files=files) == {
            "remainingDailySubmissions": 2, "remainingDailyBytes": 1024,
        }
        assert service.reserve_batch(user_id=7, submission_id="batch_2", files=files) == first
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)
