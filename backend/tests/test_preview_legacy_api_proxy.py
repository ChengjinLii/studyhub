from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches
from app.core.config import get_settings
from app.core.db import prepare_database_runtime, reset_database_runtime
from app.main import create_app


def _reset_runtime_state() -> None:
    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()


def _write_private_env(root: Path, content: str) -> Path:
    private_dir = root / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / ".env.preview").write_text(content.strip() + "\n", encoding="utf-8")
    return private_dir


def test_preview_legacy_proxy_skips_schema_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_dir = _write_private_env(
        tmp_path,
        """
        STUDYHUB_ENVIRONMENT=preview
        STUDYHUB_LEGACY_API_PROXY_BASE_URL=http://127.0.0.1:8080
        STUDYHUB_DATABASE_URL=mysql+pymysql://preview_user:preview_pass@127.0.0.1:3306/studyhub_preview
        STUDYHUB_JWT_SECRET=preview-secret-abcdefghijklmnopqrstuvwxyz
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.preview.example.com
        STUDYHUB_SMTP_FROM_EMAIL=preview@example.com
        STUDYHUB_STORAGE_PROVIDER=local_fs
        STUDYHUB_PAYMENT_PROVIDER=local_alipay
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))
    monkeypatch.setattr("app.core.db.check_database", lambda: None)
    monkeypatch.setattr(
        "app.core.db.ensure_database_schema_ready",
        lambda: (_ for _ in ()).throw(AssertionError("schema check should be skipped in legacy proxy mode")),
    )

    _reset_runtime_state()
    prepare_database_runtime()
    _reset_runtime_state()


def test_preview_legacy_proxy_intercepts_public_api_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_dir = _write_private_env(
        tmp_path,
        """
        STUDYHUB_ENVIRONMENT=preview
        STUDYHUB_LEGACY_API_PROXY_BASE_URL=http://127.0.0.1:8080
        STUDYHUB_DATABASE_URL=mysql+pymysql://preview_user:preview_pass@127.0.0.1:3306/studyhub_preview
        STUDYHUB_JWT_SECRET=preview-secret-abcdefghijklmnopqrstuvwxyz
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.preview.example.com
        STUDYHUB_SMTP_FROM_EMAIL=preview@example.com
        STUDYHUB_STORAGE_PROVIDER=local_fs
        STUDYHUB_PAYMENT_PROVIDER=local_alipay
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))
    monkeypatch.setattr("app.core.db.check_database", lambda: None)

    captured: dict[str, str] = {}

    async def fake_proxy(settings, request):
        captured["path"] = request.url.path
        captured["query"] = request.url.query
        captured["upstream"] = settings.legacy_api_proxy_base_url or ""
        return JSONResponse({"ok": True, "data": {"proxied": True}})

    monkeypatch.setattr("app.main._proxy_api_request", fake_proxy)

    _reset_runtime_state()
    with TestClient(create_app()) as client:
        response = client.get("/api/materials?page=1&size=12")

    assert response.status_code == 200
    assert response.json()["data"]["proxied"] is True
    assert captured == {
        "path": "/api/materials",
        "query": "page=1&size=12",
        "upstream": "http://127.0.0.1:8080",
    }

    _reset_runtime_state()
