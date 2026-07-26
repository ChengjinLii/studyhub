from __future__ import annotations

import pytest

from app.api.deps import clear_dependency_caches, get_auth_repo
from app.core.config import Settings, get_settings
from app.core.db import session_scope
from tests.support import build_auth_headers, seed_read_users


AGENTIC_HEALTH_PATH = "/api/admin/agent-runs/health"


@pytest.fixture()
def agentic_platform_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STUDYHUB_AGENTIC_PLATFORM_ENABLED", "true")
    get_settings.cache_clear()
    clear_dependency_caches()
    yield
    clear_dependency_caches()
    get_settings.cache_clear()


def _set_role(user_id: int, role_mask: int) -> None:
    with session_scope() as session:
        user = get_auth_repo().find_user_by_id(session, user_id)
        assert user is not None
        user.role_mask = role_mask
        get_auth_repo().save_user(session, user)


def test_admin_agentic_health_allows_only_admin(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)

    response = client.get(AGENTIC_HEALTH_PATH, headers=build_auth_headers(3, 8))

    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {"status": "ready", "runtime": "legacy"}}


def test_admin_agentic_health_rejects_developer(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)
    _set_role(1, 16)

    response = client.get(AGENTIC_HEALTH_PATH, headers=build_auth_headers(1, 16))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "Agentic research platform is admin-only"


def test_admin_agentic_health_rejects_regular_user(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)

    response = client.get(AGENTIC_HEALTH_PATH, headers=build_auth_headers(1, 1))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "Agentic research platform is admin-only"


def test_admin_agentic_health_rejects_anonymous(client, agentic_platform_enabled) -> None:
    response = client.get(AGENTIC_HEALTH_PATH)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "请先登录"


def test_admin_agentic_health_is_unavailable_when_flag_is_off(client, auth_service) -> None:
    seed_read_users(auth_service)

    response = client.get(AGENTIC_HEALTH_PATH, headers=build_auth_headers(3, 8))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "Agentic research platform is disabled"


def test_admin_agentic_health_is_not_in_openapi(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)

    response = client.get("/openapi.json", headers=build_auth_headers(3, 8))

    assert response.status_code == 200
    assert AGENTIC_HEALTH_PATH not in response.json()["paths"]


def test_agentic_platform_configuration_defaults_to_safe_values() -> None:
    settings = Settings()

    assert settings.agentic_platform_enabled is False
    assert settings.agentic_admin_only is True
    assert settings.deep_research_enabled is False
    assert settings.deep_research_web_enabled is False
    assert settings.deep_research_scholar_enabled is False
    assert settings.deep_research_python_enabled is False


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (Settings(agentic_admin_only=False), "AGENTIC_ADMIN_ONLY"),
        (Settings(agentic_runtime="unsupported"), "AGENTIC_RUNTIME"),
        (Settings(agentic_max_turns=0), "AGENTIC_MAX_TURNS"),
    ],
)
def test_agentic_platform_configuration_rejects_unsafe_values(settings: Settings, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        settings.validate_runtime_configuration()
