from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import MutableHeaders

from app.api.deps import clear_dependency_caches
from app.core.async_db import reset_async_database_runtime
from app.core.config import Settings, get_settings
from app.core.db import reset_database_runtime
from app.core.observability import get_runtime_metrics
from app.core.security_headers import apply_security_headers
from app.main import create_app


@pytest.fixture()
def csp_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
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
    monkeypatch.setenv("STUDYHUB_SECURITY_CSP", "default-src 'self'; object-src 'none'; base-uri 'self'")
    monkeypatch.setenv("STUDYHUB_SECURITY_CSP_REPORT_ONLY", "default-src 'self'; report-uri /api/security/csp-reports")

    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()
    get_runtime_metrics().clear()
    asyncio.run(reset_async_database_runtime())

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    clear_dependency_caches()
    reset_database_runtime()
    get_runtime_metrics().clear()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


def test_csp_report_only_header_is_configurable(csp_client: TestClient) -> None:
    response = csp_client.get("/api/healthz")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "default-src 'self'; object-src 'none'; base-uri 'self'"
    assert response.headers["content-security-policy-report-only"] == "default-src 'self'; report-uri /api/security/csp-reports"


def test_production_defaults_to_csp_report_only() -> None:
    headers = MutableHeaders()
    apply_security_headers(Settings(environment="production"), headers)

    assert "content-security-policy" not in headers
    report_only = headers["content-security-policy-report-only"]
    assert "default-src 'self'" in report_only
    assert "object-src 'none'" in report_only
    assert "report-uri /api/security/csp-reports" in report_only


def test_csp_report_endpoint_records_sanitized_metric(csp_client: TestClient) -> None:
    response = csp_client.post(
        "/api/security/csp-reports",
        json={"csp-report": {"violated-directive": "img-src", "blocked-uri": "https://example.com/private?token=secret"}},
    )

    assert response.status_code == 200
    metrics = csp_client.get("/api/metrics")
    assert 'studyhub_security_events_total{event="csp_report",reason="img-src"} 1' in metrics.text
    assert "token=secret" not in metrics.text
