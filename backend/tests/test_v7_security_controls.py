from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.deps import clear_dependency_caches
from app.core.async_db import reset_async_database_runtime
from app.core.config import Settings, get_settings
from app.core.db import reset_database_runtime
from app.core.rate_limit import _client_key, get_rate_limiter
from app.main import create_app
from app.services.auth_service import AuthService
from tests.test_mcp_protocol import MCP_HEADERS
from tests.support import build_auth_headers, seed_read_users


def assert_error_envelope(response, code: str, message: str) -> None:
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == {"code": code, "message": message}
    assert payload["msg"] == message
    assert "detail" not in payload
    assert response.headers["x-request-id"]


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
    monkeypatch.setenv("STUDYHUB_WRITE_ORIGIN_REQUIRE_HEADER", "true")
    monkeypatch.setenv("STUDYHUB_TRUSTED_SITE_ORIGINS", "https://study-hub.cn")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_LOGIN", "2")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_CAPTCHA", "2")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_EMAIL_VERIFICATION", "2")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_UPLOAD", "2")
    monkeypatch.setenv("STUDYHUB_RATE_LIMIT_VIEW", "2")
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


def test_auth_uses_current_database_role_over_token_claim(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)
    forged_admin_headers = build_auth_headers(1, 8)

    response = client.get("/api/admin/users", headers=forged_admin_headers)

    assert response.status_code == 403


def test_auth_rejects_token_for_missing_database_user(client: TestClient) -> None:
    missing_user_headers = build_auth_headers(999_999, 8)

    response = client.get("/api/admin/users", headers=missing_user_headers)

    assert response.status_code == 401


def test_write_origin_protection_rejects_cross_site_write(strict_security_client: TestClient) -> None:
    response = strict_security_client.post("/api/session", headers={"Origin": "https://evil.example"}, json={})

    assert response.status_code == 403
    assert_error_envelope(response, "ORIGIN_FORBIDDEN", "Write request origin is not allowed")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_write_origin_protection_allows_trusted_origin(strict_security_client: TestClient) -> None:
    response = strict_security_client.post("/api/session", headers={"Origin": "https://study-hub.cn"}, json={})

    assert response.status_code == 400


def test_write_origin_protection_rejects_missing_origin_for_cookie_writes(strict_security_client: TestClient) -> None:
    response = strict_security_client.post("/api/session", headers={"Cookie": "studyhub_token=stale-token"}, json={})

    assert response.status_code == 403
    assert_error_envelope(response, "ORIGIN_FORBIDDEN", "Write request origin is required")


def test_write_origin_protection_allows_missing_origin_without_cookie(strict_security_client: TestClient) -> None:
    response = strict_security_client.post("/api/session", json={})

    assert response.status_code == 400


def test_write_origin_protection_allows_bearer_writes_without_origin(strict_security_client: TestClient) -> None:
    response = strict_security_client.post(
        "/api/materials",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code in {401, 422}


def test_login_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    payload = {"username": "nobody", "password": "bad", "captchaId": "missing", "captcha": "0000"}

    for _ in range(2):
        assert strict_security_client.post("/api/session", json=payload).status_code in {400, 401}
    response = strict_security_client.post("/api/session", json=payload)

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many login requests")


def test_captcha_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    assert strict_security_client.get("/api/captchas").status_code == 200
    assert strict_security_client.get("/api/captchas").status_code == 200

    response = strict_security_client.get("/api/captchas")

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many captcha requests")


def test_mcp_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "materials.discover", "arguments": {"query": "数据结构", "limit": 1}},
    }

    assert strict_security_client.post("/mcp", headers=MCP_HEADERS, json=payload).status_code == 200
    assert strict_security_client.post("/mcp", headers=MCP_HEADERS, json=payload).status_code == 200

    response = strict_security_client.post("/mcp", headers=MCP_HEADERS, json=payload)

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many mcp requests")


def test_material_upload_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    for _ in range(2):
        assert strict_security_client.post("/api/materials").status_code in {400, 401, 422}

    response = strict_security_client.post("/api/materials")

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many upload requests")


def test_material_view_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    for index in range(2):
        response = strict_security_client.post("/api/materials/101/view", json={"viewerToken": f"viewer-{index}"})
        assert response.status_code == 200

    response = strict_security_client.post("/api/materials/101/view", json={"viewerToken": "viewer-over-limit"})

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many view requests")


def test_market_publish_rate_limit_returns_429_from_same_bucket(strict_security_client: TestClient) -> None:
    for _ in range(2):
        assert strict_security_client.post("/api/market").status_code in {400, 401, 422}

    response = strict_security_client.post("/api/market")

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many upload requests")


def test_registration_verification_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    payload = {"username": "alice", "email": "alice@example.com", "password": "secret123", "captchaId": "missing", "captchaCode": "0000"}

    for _ in range(2):
        assert strict_security_client.post("/api/registration-verifications", json=payload).status_code in {400, 401}

    response = strict_security_client.post("/api/registration-verifications", json=payload)

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many email-verification requests")


def test_password_reset_rate_limit_returns_429(strict_security_client: TestClient) -> None:
    payload = {"identifier": "alice", "newPassword": "secret123", "captchaId": "missing", "captchaCode": "0000"}

    for _ in range(2):
        assert strict_security_client.post("/api/password-resets", json=payload).status_code in {400, 401}

    response = strict_security_client.post("/api/password-resets", json=payload)

    assert response.status_code == 429
    assert_error_envelope(response, "RATE_LIMITED", "Too many email-verification requests")


def _request_with_client(host: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/session",
            "headers": headers,
            "client": (host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_rate_limit_ignores_forwarded_for_from_untrusted_clients() -> None:
    settings = Settings(trusted_proxy_ips="10.0.0.1")
    request = _request_with_client("203.0.113.9", "198.51.100.7")

    assert _client_key(settings, request) == "203.0.113.9"


def test_rate_limit_accepts_forwarded_for_from_trusted_proxy() -> None:
    settings = Settings(trusted_proxy_ips="10.0.0.0/24")
    request = _request_with_client("10.0.0.8", "198.51.100.7, 10.0.0.8")

    assert _client_key(settings, request) == "198.51.100.7"


def test_docs_can_be_disabled_by_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv("STUDYHUB_DOCS_ENABLED", "false")

    get_settings.cache_clear()
    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    app = create_app()
    with TestClient(app) as test_client:
        assert test_client.get("/openapi.json").status_code == 404
        assert test_client.get("/docs").status_code == 404
    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


def test_trusted_host_middleware_can_reject_unconfigured_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv("STUDYHUB_TRUSTED_HOSTS", "testserver,study-hub.cn")

    get_settings.cache_clear()
    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    app = create_app()
    with TestClient(app) as test_client:
        assert test_client.get("/api/healthz").status_code == 200
        assert test_client.get("/api/healthz", headers={"Host": "evil.example"}).status_code == 400
    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()
