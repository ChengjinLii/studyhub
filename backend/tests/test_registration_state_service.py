from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services.registration_state_service import RegistrationStateService


def test_registration_code_allows_retry_then_issues_one_time_ticket() -> None:
    service = RegistrationStateService(
        Settings(environment="test", security_state_backend="local", verification_max_attempts=3)
    )
    issue = service.create_verification(
        email="registration-state@example.com",
        username="registration_state",
        password_hash="$2b$test-only-hash",
    )

    with pytest.raises(HTTPException) as wrong:
        service.issue_ticket(email=issue.email, code="000000" if issue.code != "000000" else "111111")
    assert wrong.value.status_code == 400

    token, _ = service.issue_ticket(email=issue.email, code=issue.code)
    credentials = service.consume_ticket(token)
    assert credentials.username == "registration_state"
    with pytest.raises(HTTPException) as replay:
        service.consume_ticket(token)
    assert replay.value.status_code == 409


def test_registration_state_fails_closed_when_redis_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    service = RegistrationStateService(
        Settings(
            environment="production",
            security_state_backend="redis",
            redis_url="redis://cache.invalid",
        )
    )

    def unavailable():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(service, "_client", unavailable)
    with pytest.raises(HTTPException) as failure:
        service.create_verification(
            email="redis-down@example.com",
            username="redis_down",
            password_hash="$2b$test-only-hash",
        )
    assert failure.value.status_code == 503
