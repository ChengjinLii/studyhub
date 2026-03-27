from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import (
    clear_dependency_caches,
    get_comments_service,
    get_db_session,
    get_leaderboard_read_service,
    get_market_service,
    get_materials_service,
    get_requests_service,
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


def _preview_private_dir(tmp_path: Path) -> Path:
    return _write_private_env(
        tmp_path,
        """
        STUDYHUB_ENVIRONMENT=preview
        STUDYHUB_DATABASE_URL=mysql+pymysql://preview_user:preview_pass@127.0.0.1:3306/studyhub_preview
        STUDYHUB_JWT_SECRET=preview-secret-abcdefghijklmnopqrstuvwxyz
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.preview.example.com
        STUDYHUB_SMTP_FROM_EMAIL=preview@example.com
        STUDYHUB_STORAGE_PROVIDER=local_fs
        STUDYHUB_PAYMENT_PROVIDER=local_alipay
        """,
    )


def test_preview_runtime_allows_partial_schema_compatibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_dir = _preview_private_dir(tmp_path)
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))
    monkeypatch.setattr("app.core.db.check_database", lambda: None)
    monkeypatch.setattr(
        "app.core.db.ensure_database_schema_ready",
        lambda: (_ for _ in ()).throw(AssertionError("preview compatibility mode should skip full schema enforcement")),
    )

    _reset_runtime_state()
    prepare_database_runtime()
    _reset_runtime_state()


def test_preview_public_read_routes_stay_local_without_java_proxy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_dir = _preview_private_dir(tmp_path)
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))
    monkeypatch.setattr("app.core.db.check_database", lambda: None)
    monkeypatch.setattr("app.core.db.ensure_database_schema_ready", lambda: None)

    class FakeMaterialsService:
        def list_materials(self, *args, **kwargs):
            return {"items": [{"id": 1}], "meta": {"page": 1, "size": 2, "total": 1}, "stats": {}, "availableTags": []}

    class FakeMarketService:
        def list_market(self, *args, **kwargs):
            return {"items": [{"id": 9}], "meta": {"page": 1, "size": 2, "total": 1}, "stats": {}}

        def get_detail(self, *args, **kwargs):
            return {"id": 9, "title": "market"}

    class FakeLeaderboardService:
        def get_contributors(self, *args, **kwargs):
            return [{"userId": 6, "downloads": 10, "roleMask": 1, "username": "tester"}]

    class FakeCommentsService:
        def list_comments(self, *args, **kwargs):
            return {"items": [{"id": 11}], "meta": {"page": 0, "size": 5, "total": 1}}

        def list_replies(self, *args, **kwargs):
            return {"items": [{"id": 22}], "meta": {"page": 0, "size": 5, "total": 1}}

    class FakeRequestsService:
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

    _reset_runtime_state()
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: object()
    app.dependency_overrides[get_materials_service] = lambda: FakeMaterialsService()
    app.dependency_overrides[get_market_service] = lambda: FakeMarketService()
    app.dependency_overrides[get_leaderboard_read_service] = lambda: FakeLeaderboardService()
    app.dependency_overrides[get_comments_service] = lambda: FakeCommentsService()
    app.dependency_overrides[get_requests_service] = lambda: FakeRequestsService()

    with TestClient(app) as client:
        materials_response = client.get("/api/materials?page=1&size=2")
        market_response = client.get("/api/market?page=1&size=2")
        market_detail_response = client.get("/api/market/9")
        leaderboard_response = client.get("/api/leaderboard/contributors?limit=3&period=all")
        requests_response = client.get("/api/requests?sort=hot&limit=5")
        request_leaderboard_response = client.get("/api/requests/leaderboard?limit=5")
        comments_response = client.get("/api/comments?materialId=106&page=0&size=5")
        replies_response = client.get("/api/comments/12/replies?page=0&size=5")
        captcha_response = client.get("/api/auth/captcha")

    assert materials_response.status_code == 200
    assert materials_response.json()["data"]["items"] == [{"id": 1}]
    assert market_response.status_code == 200
    assert market_response.json()["data"]["items"] == [{"id": 9}]
    assert market_detail_response.status_code == 200
    assert market_detail_response.json()["data"]["id"] == 9
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
    assert captcha_response.status_code == 200
    assert "x-studyhub-preview-upstream" not in materials_response.headers
    assert "x-studyhub-preview-upstream" not in captcha_response.headers

    _reset_runtime_state()
