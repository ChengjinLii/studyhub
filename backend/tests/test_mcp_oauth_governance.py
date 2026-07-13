from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from fastapi.testclient import TestClient
import jwt
import pytest

from app.api.deps import clear_dependency_caches
from app.core.async_db import reset_async_database_runtime
from app.core.config import Settings, get_settings
from app.core.db import reset_database_runtime
from app.core.rate_limit import get_rate_limiter
from app.main import create_app
from app.mcp.auth import McpPrincipal
from app.mcp.governance import check_mcp_client_budget
from tests.test_mcp_search_fetch import call_tool


@pytest.fixture()
def oauth_mcp_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
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
    monkeypatch.setenv("STUDYHUB_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("STUDYHUB_MCP_OAUTH_AUTHORIZATION_SERVERS", "https://auth.example.edu")
    monkeypatch.setenv("STUDYHUB_MCP_OAUTH_ISSUER", "https://auth.example.edu")
    monkeypatch.setenv("STUDYHUB_MCP_OAUTH_JWKS_URI", "https://auth.example.edu/.well-known/jwks.json")
    monkeypatch.setenv("STUDYHUB_MCP_OAUTH_AUDIENCE", "https://study-hub.cn/mcp")
    monkeypatch.setattr("app.mcp.auth._oauth_signing_key", lambda jwks_uri, token: private_key.public_key())

    get_settings.cache_clear()
    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    app = create_app()

    def issue_token(*, audience: str = "https://study-hub.cn/mcp", scope: str = "mcp:materials.search") -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "iss": "https://auth.example.edu",
                "sub": "user-306",
                "client_id": "external-study-agent",
                "aud": audience,
                "scope": scope,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=10)).timestamp()),
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    with TestClient(app) as test_client:
        yield test_client, issue_token

    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


def test_mcp_accepts_audience_bound_oauth_access_token(oauth_mcp_client) -> None:
    client, issue_token = oauth_mcp_client
    response = call_tool(
        client,
        "materials.search",
        {"query": "数据结构", "limit": 1},
        headers={"Authorization": f"Bearer {issue_token()}"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["items"]


def test_mcp_rejects_oauth_token_for_another_audience(oauth_mcp_client) -> None:
    client, issue_token = oauth_mcp_client
    response = call_tool(
        client,
        "materials.search",
        {"query": "数据结构", "limit": 1},
        headers={"Authorization": f"Bearer {issue_token(audience='https://other.example/mcp')}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MCP_UNAUTHORIZED"


def test_mcp_oauth_metadata_advertises_real_authorization_server(oauth_mcp_client) -> None:
    client, _ = oauth_mcp_client
    response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json()["authorization_servers"] == ["https://auth.example.edu"]
    assert response.json()["resource"] == "https://study-hub.cn/mcp"


def test_mcp_audit_log_excludes_raw_subject_and_token(oauth_mcp_client, caplog) -> None:
    client, issue_token = oauth_mcp_client
    token = issue_token()
    caplog.set_level(logging.INFO, logger="app.main")

    response = call_tool(
        client,
        "materials.search",
        {"query": "数据结构", "limit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    records = [record for record in caplog.records if getattr(record, "event", None) == "mcp_access_audit"]
    assert records
    assert records[-1].client_id == "external-study-agent"
    assert records[-1].subject_hash != "user-306"
    assert token not in records[-1].getMessage()


def _quota_request(client_id: str) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/mcp", "headers": [], "client": ("127.0.0.1", 1)})
    request.state.mcp_principal = McpPrincipal(
        client_id=client_id,
        subject="user-1",
        scopes=frozenset({"mcp:materials.search"}),
        auth_method="oauth",
    )
    return request


def test_mcp_client_rate_limit_isolated_by_authenticated_client() -> None:
    settings = Settings(
        environment="test",
        rate_limit_backend="local",
        rate_limit_window_seconds=60,
        mcp_client_rate_limit=2,
        mcp_client_quota=20,
    )
    get_rate_limiter().clear()

    assert check_mcp_client_budget(settings, _quota_request("client-a"))[0] is True
    assert check_mcp_client_budget(settings, _quota_request("client-a"))[0] is True
    allowed, reason, retry_after = check_mcp_client_budget(settings, _quota_request("client-a"))
    assert allowed is False
    assert reason == "MCP client rate limit exceeded"
    assert retry_after == 60
    assert check_mcp_client_budget(settings, _quota_request("client-b"))[0] is True
    get_rate_limiter().clear()


def test_mcp_client_period_quota_is_enforced() -> None:
    settings = Settings(
        environment="test",
        rate_limit_backend="local",
        rate_limit_window_seconds=60,
        mcp_client_rate_limit=20,
        mcp_client_quota=2,
        mcp_client_quota_window_seconds=3600,
    )
    get_rate_limiter().clear()

    assert check_mcp_client_budget(settings, _quota_request("client-a"))[0] is True
    assert check_mcp_client_budget(settings, _quota_request("client-a"))[0] is True
    allowed, reason, retry_after = check_mcp_client_budget(settings, _quota_request("client-a"))
    assert allowed is False
    assert reason == "MCP client quota exceeded"
    assert retry_after == 3600
    get_rate_limiter().clear()
