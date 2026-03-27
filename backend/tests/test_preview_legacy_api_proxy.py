from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.deps import (
    clear_dependency_caches,
    get_db_session,
    get_legacy_comments_read_service,
    get_legacy_leaderboard_read_service,
    get_legacy_market_read_service,
    get_legacy_materials_read_service,
    get_legacy_requests_read_service,
)
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


def test_preview_legacy_proxy_intercepts_non_exempt_api_requests(
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
        response = client.get("/api/auth/captcha")

    assert response.status_code == 200
    assert response.json()["data"]["proxied"] is True
    assert captured == {
        "path": "/api/auth/captcha",
        "query": "",
        "upstream": "http://127.0.0.1:8080",
    }

    _reset_runtime_state()


def test_preview_direct_read_routes_bypass_proxy(
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

    async def fail_proxy(*args, **kwargs):
        raise AssertionError("selected public read routes should stay local")

    class FakeLegacyMaterialsService:
        def list_materials(self, *args, **kwargs):
            return {"items": [{"id": 1}], "meta": {"page": 1, "size": 2, "total": 1}, "stats": {}, "availableTags": []}

    class FakeLegacyMarketService:
        def list_market(self, *args, **kwargs):
            return {"items": [{"id": 9}], "meta": {"page": 1, "size": 2, "total": 1}, "stats": {}}

    class FakeLegacyLeaderboardService:
        def get_contributors(self, *args, **kwargs):
            return [{"userId": 6, "downloads": 10, "roleMask": 1, "username": "tester"}]

    class FakeLegacyCommentsService:
        def list_comments(self, *args, **kwargs):
            return {"items": [{"id": 11}], "meta": {"page": 0, "size": 5, "total": 1}}

        def list_replies(self, *args, **kwargs):
            return {"items": [{"id": 22}], "meta": {"page": 0, "size": 5, "total": 1}}

    class FakeLegacyRequestsService:
        def list_requests(self, *args, **kwargs):
            return [{"id": 31}]

        def list_leaderboard(self, *args, **kwargs):
            return [{"id": 32}]

        def get_detail(self, *args, **kwargs):
            return {"id": 33}

        def get_responses(self, *args, **kwargs):
            return [{"id": 34}]

        def get_contributions(self, *args, **kwargs):
            return [{"id": 35}]

    monkeypatch.setattr("app.main._proxy_api_request", fail_proxy)

    _reset_runtime_state()
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: object()
    app.dependency_overrides[get_legacy_materials_read_service] = lambda: FakeLegacyMaterialsService()
    app.dependency_overrides[get_legacy_market_read_service] = lambda: FakeLegacyMarketService()
    app.dependency_overrides[get_legacy_leaderboard_read_service] = lambda: FakeLegacyLeaderboardService()
    app.dependency_overrides[get_legacy_comments_read_service] = lambda: FakeLegacyCommentsService()
    app.dependency_overrides[get_legacy_requests_read_service] = lambda: FakeLegacyRequestsService()

    with TestClient(app) as client:
        materials_response = client.get("/api/materials?page=1&size=2")
        market_response = client.get("/api/market?page=1&size=2")
        leaderboard_response = client.get("/api/leaderboard/contributors?limit=3&period=all")
        requests_response = client.get("/api/requests?sort=hot&limit=5")
        request_leaderboard_response = client.get("/api/requests/leaderboard?limit=5")
        comments_response = client.get("/api/comments?materialId=106&page=0&size=5")
        replies_response = client.get("/api/comments/12/replies?page=0&size=5")

    assert materials_response.status_code == 200
    assert materials_response.json()["data"]["items"] == [{"id": 1}]
    assert market_response.status_code == 200
    assert market_response.json()["data"]["items"] == [{"id": 9}]
    assert leaderboard_response.status_code == 200
    assert leaderboard_response.json()["data"] == [{"userId": 6, "downloads": 10, "roleMask": 1, "username": "tester"}]
    assert requests_response.status_code == 200
    assert requests_response.json()["data"] == [{"id": 31}]
    assert request_leaderboard_response.status_code == 200
    assert request_leaderboard_response.json()["data"] == [{"id": 32}]
    assert comments_response.status_code == 200
    assert comments_response.json()["data"]["items"] == [{"id": 11}]
    assert replies_response.status_code == 200
    assert replies_response.json()["data"]["items"] == [{"id": 22}]

    _reset_runtime_state()
