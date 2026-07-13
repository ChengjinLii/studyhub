from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches, get_captcha_service
from app.core.async_db import reset_async_database_runtime
from app.core.config import Settings, get_settings
from app.core.db import reset_database_runtime
from app.main import create_app
from app.mcp.auth import origin_allowed
from tests.test_mcp_search_fetch import call_tool


def assert_middleware_error(response, code: str, message: str) -> None:
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == {"code": code, "message": message}
    assert payload["msg"] == message
    assert "detail" not in payload
    assert response.headers["x-request-id"]


@pytest.fixture()
def origin_locked_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "studyhub-fastapi-test.sqlite3"
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "test")
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")
    monkeypatch.setenv("STUDYHUB_CONTRACT_REPORT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("STUDYHUB_MATERIAL_ASSET_DIR", str(tmp_path / "materials"))
    monkeypatch.setenv("STUDYHUB_MARKET_ASSET_DIR", str(tmp_path / "market"))
    monkeypatch.setenv("STUDYHUB_PAYOUT_QR_ASSET_DIR", str(tmp_path / "payout-qr"))
    monkeypatch.setenv("STUDYHUB_MAIL_OUTBOX_DIR", str(tmp_path / "outbox" / "mail"))
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_BOOTSTRAP_USER", "false")
    monkeypatch.setenv("STUDYHUB_MCP_ALLOWED_ORIGINS", "https://study-hub.cn")

    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()
    import asyncio

    asyncio.run(reset_async_database_runtime())

    app = create_app()
    with TestClient(app) as test_client:
        get_captcha_service().reset()
        yield test_client

    clear_dependency_caches()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


@pytest.fixture()
def auth_required_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "studyhub-fastapi-test.sqlite3"
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "test")
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")
    monkeypatch.setenv("STUDYHUB_CONTRACT_REPORT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("STUDYHUB_MATERIAL_ASSET_DIR", str(tmp_path / "materials"))
    monkeypatch.setenv("STUDYHUB_MARKET_ASSET_DIR", str(tmp_path / "market"))
    monkeypatch.setenv("STUDYHUB_PAYOUT_QR_ASSET_DIR", str(tmp_path / "payout-qr"))
    monkeypatch.setenv("STUDYHUB_MAIL_OUTBOX_DIR", str(tmp_path / "outbox" / "mail"))
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_BOOTSTRAP_USER", "false")
    monkeypatch.setenv("STUDYHUB_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setenv("STUDYHUB_MCP_ACCESS_TOKEN", "test-mcp-token")

    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()
    import asyncio

    asyncio.run(reset_async_database_runtime())

    app = create_app()
    with TestClient(app) as test_client:
        get_captcha_service().reset()
        yield test_client

    clear_dependency_caches()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


@pytest.fixture()
def scoped_mcp_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "studyhub-fastapi-test.sqlite3"
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "test")
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")
    monkeypatch.setenv("STUDYHUB_CONTRACT_REPORT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("STUDYHUB_MATERIAL_ASSET_DIR", str(tmp_path / "materials"))
    monkeypatch.setenv("STUDYHUB_MARKET_ASSET_DIR", str(tmp_path / "market"))
    monkeypatch.setenv("STUDYHUB_PAYOUT_QR_ASSET_DIR", str(tmp_path / "payout-qr"))
    monkeypatch.setenv("STUDYHUB_MAIL_OUTBOX_DIR", str(tmp_path / "outbox" / "mail"))
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_BOOTSTRAP_USER", "false")
    monkeypatch.setenv("STUDYHUB_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setenv(
        "STUDYHUB_MCP_ACCESS_TOKENS",
        (
            "read-token:studyhub.read;"
            "search-token:mcp:materials.search;"
            "recommend-token:mcp:materials.recommend;"
            "detail-token:mcp:materials.read;"
            "policy-token:mcp:policy.read;"
            "legacy-token:mcp:discover_public_materials;"
            "unrelated-token:other.scope"
        ),
    )

    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()
    import asyncio

    asyncio.run(reset_async_database_runtime())

    app = create_app()
    with TestClient(app) as test_client:
        get_captcha_service().reset()
        yield test_client

    clear_dependency_caches()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


def test_mcp_allows_anonymous_public_tools_in_local_test(client: TestClient) -> None:
    response = call_tool(client, "materials.search", {"query": "数据结构", "limit": 1})

    assert response.status_code == 200
    assert "items" in response.json()["result"]["structuredContent"]


@pytest.mark.parametrize("tool", ["health.ready", "comments.create", "admin.users.search", "market.search"])
def test_mcp_rejects_every_non_public_tool_at_protocol_boundary(client: TestClient, tool: str) -> None:
    response = call_tool(client, tool)

    assert response.status_code == 403
    assert_middleware_error(response, "MCP_FORBIDDEN", "MCP method or tool is not allowed")


def test_mcp_rejects_invalid_origin_when_origin_validation_enabled(origin_locked_client: TestClient) -> None:
    response = origin_locked_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Origin": "https://evil.example",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 403
    assert_middleware_error(response, "MCP_FORBIDDEN", "MCP Origin is not allowed")


def test_mcp_rejects_browser_origin_by_default_in_production() -> None:
    settings = Settings(environment="production")

    assert origin_allowed(settings, None) is True
    assert origin_allowed(settings, "https://study-hub.cn") is False


def test_mcp_is_disabled_by_default_in_production_settings() -> None:
    settings = Settings(environment="production")

    assert settings.resolved_mcp_enabled is False
    assert settings.resolved_mcp_require_auth is True


def test_mcp_require_auth_rejects_anonymous_requests(auth_required_client: TestClient) -> None:
    response = call_tool(auth_required_client, "materials.search", {"query": "数据结构", "limit": 1})

    assert response.status_code == 401
    assert_middleware_error(response, "MCP_UNAUTHORIZED", "MCP authentication required")
    assert response.headers["WWW-Authenticate"].startswith("Bearer ")
    assert "resource_metadata=" in response.headers["WWW-Authenticate"]


def test_mcp_require_auth_rejects_invalid_bearer_token(auth_required_client: TestClient) -> None:
    response = call_tool(
        auth_required_client,
        "materials.search",
        {"query": "数据结构", "limit": 1},
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert_middleware_error(response, "MCP_UNAUTHORIZED", "MCP authentication required")
    assert response.headers["WWW-Authenticate"].startswith("Bearer ")
    assert "resource_metadata=" in response.headers["WWW-Authenticate"]


def test_mcp_require_auth_accepts_configured_bearer_token(auth_required_client: TestClient) -> None:
    response = call_tool(
        auth_required_client,
        "materials.search",
        {"query": "数据结构", "limit": 1},
        headers={"Authorization": "Bearer test-mcp-token"},
    )

    assert response.status_code == 200
    assert "items" in response.json()["result"]["structuredContent"]


def test_mcp_scoped_read_token_allows_read_tool(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "materials.search",
        {"query": "数据结构", "limit": 1},
        headers={"Authorization": "Bearer read-token"},
    )

    assert response.status_code == 200
    assert "items" in response.json()["result"]["structuredContent"]


def test_mcp_scoped_search_token_allows_only_search_tool(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "materials.search",
        {"query": "数据结构", "limit": 2},
        headers={"Authorization": "Bearer search-token"},
    )

    assert response.status_code == 200
    item = response.json()["result"]["structuredContent"]["items"][0]
    assert set(item).issuperset({"materialId", "title", "url", "reason"})
    assert "ref=mcp" in item["url"]


def test_mcp_scoped_recommend_token_allows_public_recommendation(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "materials.recommend",
        {"query": "数据结构", "limit": 2},
        headers={"Authorization": "Bearer recommend-token"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["items"]


def test_mcp_scoped_detail_token_allows_material_detail(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "materials.get",
        {"material_id": 101},
        headers={"Authorization": "Bearer detail-token"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["url"].endswith("/materials/101?ref=mcp")


def test_mcp_scoped_policy_token_allows_policy_tool(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "platform.policy",
        {"question": "怎么下载资料"},
        headers={"Authorization": "Bearer policy-token"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["policies"]


def test_mcp_scoped_search_token_cannot_read_detail(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "materials.get",
        {"material_id": 101},
        headers={"Authorization": "Bearer search-token"},
    )

    assert response.status_code == 403
    assert_middleware_error(response, "MCP_FORBIDDEN", "MCP scope is not allowed")


def test_mcp_scoped_token_without_read_scope_rejects_tools_list(scoped_mcp_client: TestClient) -> None:
    response = scoped_mcp_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": "Bearer unrelated-token",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 403
    assert_middleware_error(response, "MCP_FORBIDDEN", "MCP scope is not allowed")


def test_mcp_auth_required_rejects_unknown_tools_before_sdk(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "materials.download.create",
        {"id": 101},
        headers={"Authorization": "Bearer read-token"},
    )

    assert response.status_code == 403
    assert_middleware_error(response, "MCP_FORBIDDEN", "MCP method or tool is not allowed")


def test_mcp_auth_required_rejects_json_rpc_batch(scoped_mcp_client: TestClient) -> None:
    response = scoped_mcp_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": "Bearer read-token",
        },
        json=[
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ],
    )

    assert response.status_code == 403
    assert_middleware_error(response, "MCP_FORBIDDEN", "MCP batch requests are not allowed")


def test_mcp_legacy_discovery_scope_remains_valid_during_scope_migration(scoped_mcp_client: TestClient) -> None:
    response = call_tool(
        scoped_mcp_client,
        "materials.search",
        {"query": "数据结构", "limit": 1},
        headers={"Authorization": "Bearer legacy-token"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["items"]


def test_mcp_legacy_discovery_scope_can_list_public_tools(scoped_mcp_client: TestClient) -> None:
    response = scoped_mcp_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": "Bearer legacy-token",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 200
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
        "materials.search",
        "materials.get",
        "materials.recommend",
        "platform.policy",
    }
