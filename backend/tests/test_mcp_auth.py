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


def test_mcp_allows_anonymous_read_tools_in_local_test(client: TestClient) -> None:
    response = call_tool(client, "health.ready")

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["status"] == "ok"


def test_mcp_rejects_unexposed_write_and_admin_tools(client: TestClient) -> None:
    write_response = call_tool(client, "comments.create", {"materialId": 101, "content": "hello"})
    admin_response = call_tool(client, "admin.users.search", {"query": "alice"})

    assert write_response.status_code == 200
    assert write_response.json()["result"]["isError"] is True
    assert "Unknown tool" in write_response.json()["result"]["content"][0]["text"]
    assert admin_response.status_code == 200
    assert admin_response.json()["result"]["isError"] is True
    assert "Unknown tool" in admin_response.json()["result"]["content"][0]["text"]


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


def test_mcp_rejects_browser_origin_by_default_in_production() -> None:
    settings = Settings(environment="production")

    assert origin_allowed(settings, None) is True
    assert origin_allowed(settings, "https://study-hub.cn") is False
