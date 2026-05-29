from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches, get_auth_service, get_captcha_service
from app.core.async_db import reset_async_database_runtime
from app.core.config import get_settings
from app.core.db import reset_database_runtime
from app.core.rate_limit import get_rate_limiter
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
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

    get_settings.cache_clear()
    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    import asyncio

    asyncio.run(reset_async_database_runtime())

    app = create_app()
    with TestClient(app) as test_client:
        get_captcha_service().reset()
        yield test_client

    clear_dependency_caches()
    get_rate_limiter().clear()
    reset_database_runtime()
    asyncio.run(reset_async_database_runtime())
    get_settings.cache_clear()


@pytest.fixture()
def auth_service():
    return get_auth_service()


@pytest.fixture()
def captcha_service():
    return get_captcha_service()
