from __future__ import annotations

from pathlib import Path
import json

from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches, get_captcha_service
from app.core.config import get_settings
from app.core.db import reset_database_runtime, session_scope
from app.main import create_app
from app.repos.auth_repo import AuthRepository


def _build_local_dev_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "local-dev")
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_ROOT_DIR", str(tmp_path / ".local-dev"))
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")

    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()
    return TestClient(create_app())


def test_local_dev_bootstraps_developer_and_supports_quick_login(tmp_path: Path, monkeypatch) -> None:
    with _build_local_dev_client(tmp_path, monkeypatch) as client:
        health_response = client.get("/api/healthz")
        assert health_response.status_code == 200
        health_data = health_response.json()["data"]
        assert health_data["environment"] == "local-dev"
        assert health_data["providers"] == {
            "mail": "local_outbox",
            "storage": "local_fs",
            "payment": "local_alipay",
            "transfer": "local_transfer",
            "kyc": "mock_local",
            "lock": "db_row",
        }
        assert health_data["localDev"] == {
            "enabled": True,
            "quickLoginEnabled": True,
            "developerUsername": "developer",
        }

        with session_scope() as session:
            developer = AuthRepository().find_user_by_username(session, "developer")
            assert developer is not None
            assert developer.id == 900001
            assert developer.nickname == "开发者"

        login_response = client.post("/api/auth/dev-login")
        assert login_response.status_code == 200
        payload = login_response.json()["data"]
        assert payload["user"]["id"] == 900001
        assert payload["user"]["username"] == "developer"

        session_response = client.get("/api/session")
        assert session_response.status_code == 200
        session_user = session_response.json()["data"]["user"]
        assert session_user["id"] == 900001
        assert session_user["username"] == "developer"
        assert session_user["nickname"] == "开发者"

    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()


def test_local_dev_register_writes_mail_outbox(tmp_path: Path, monkeypatch) -> None:
    with _build_local_dev_client(tmp_path, monkeypatch) as client:
        captcha_response = client.get("/api/auth/captcha")
        assert captcha_response.status_code == 200
        captcha_id = captcha_response.json()["data"]["captchaId"]
        captcha_code = get_captcha_service().peek_code_for_testing(captcha_id)
        assert captcha_code is not None

        outbox_dir = tmp_path / ".local-dev" / "outbox" / "mail"
        outbox_before = list(outbox_dir.glob("*.json"))

        register_response = client.post(
            "/api/auth/register",
            json={
                "username": "mail_dev",
                "email": "mail_dev@example.com",
                "password": "secret123",
                "captchaId": captcha_id,
                "captchaCode": captcha_code,
            },
        )
        assert register_response.status_code == 200, register_response.text

        outbox_after = sorted(outbox_dir.glob("*.json"))
        assert len(outbox_after) == len(outbox_before) + 1
        latest_mail = json.loads(outbox_after[-1].read_text(encoding="utf-8"))
        assert latest_mail["email"] == "mail_dev@example.com"
        assert latest_mail["purpose"] == "REGISTER"
        assert latest_mail["code"]
        assert "StudyHub local-dev" in latest_mail["subject"]

    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()


def test_dev_login_is_hidden_outside_local_dev(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "test")
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.sqlite3'}")
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")

    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()

    with TestClient(create_app()) as client:
        response = client.post("/api/auth/dev-login")
        assert response.status_code == 404

    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()


def test_local_dev_allows_localhost_cors_on_public_and_auth_failures(tmp_path: Path, monkeypatch) -> None:
    with _build_local_dev_client(tmp_path, monkeypatch) as client:
        origin = "http://127.0.0.1:3101"

        captcha_response = client.get("/api/auth/captcha", headers={"Origin": origin})
        assert captcha_response.status_code == 200
        assert captcha_response.headers["access-control-allow-origin"] == origin
        assert captcha_response.headers["access-control-allow-credentials"] == "true"

        summary_response = client.get("/api/notifications/summary", headers={"Origin": origin})
        assert summary_response.status_code == 401
        assert summary_response.headers["access-control-allow-origin"] == origin
        assert summary_response.headers["access-control-allow-credentials"] == "true"

    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()
