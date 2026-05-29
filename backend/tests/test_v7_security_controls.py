from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches
from app.core.async_db import reset_async_database_runtime
from app.core.config import get_settings
from app.core.db import reset_database_runtime
from app.core.rate_limit import get_rate_limiter
from app.main import create_app
from tests.test_mcp_protocol import MCP_HEADERS


@pytest.fixture()
def strict_security_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
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
    monkeypatch.setenv("STUDYHUB_WRITE_ORIGIN_PROTECTION_ENABLED", "true")
    monkeypatch.setenv("STUDYHUB_TRUSTED_SITE_ORIGINS", "https://study-hub.cn")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_LOGIN", "2")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_CAPTCHA", "2")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_UPLOAD", "2")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_MCP", "2")

    get_settings.cache_clear()
    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


def test_api_responses_include_security_headers(client: TestClient) -> None:
    response = client.get("/api/healthz")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]


def test_write_origin_protection_rejects_cross_site_write(strict_security_client: TestClient) -> None:
    response = strict_security_client.post("/api/session", headers={"Origin": "https://evil.example"}, json={})

    assert response.status_code == 403
    assert response.json()["detail"] == "Write request origin is not allowed"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_write_origin_protection_allows_trusted_origin(strict_security_client: TestClient) -> None:
    response = strict_security_client.post("/api/session", headers={"Origin": "https://study-hub.cn"}, json={})

    assert response.status_code == 400


def test_login_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    payload = {"username": "nobody", "password": "bad", "captchaId": "missing", "captcha": "0000"}

    for _ in range(2):
        assert strict_security_client.post("/api/session", json=payload).status_code in {400, 401}
    response = strict_security_client.post("/api/session", json=payload)

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many login requests"


def test_captcha_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    assert strict_security_client.get("/api/captchas").status_code == 200
    assert strict_security_client.get("/api/captchas").status_code == 200

    response = strict_security_client.get("/api/captchas")

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many captcha requests"


def test_mcp_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "health.ready", "arguments": {}},
    }

    assert strict_security_client.post("/mcp", headers=MCP_HEADERS, json=payload).status_code == 200
    assert strict_security_client.post("/mcp", headers=MCP_HEADERS, json=payload).status_code == 200

    response = strict_security_client.post("/mcp", headers=MCP_HEADERS, json=payload)

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many mcp requests"
