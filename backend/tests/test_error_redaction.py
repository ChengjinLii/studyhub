from __future__ import annotations

from app.services.health_service import HealthService


def test_readiness_probe_does_not_expose_provider_error_details() -> None:
    service = object.__new__(HealthService)

    def fail_probe() -> dict[str, object]:
        raise RuntimeError("mysql://admin:private-password@database.internal/studyhub")

    result = service._probe(fail_probe)

    assert result == {"status": "error", "message": "Dependency probe failed"}
    assert "private-password" not in str(result)
