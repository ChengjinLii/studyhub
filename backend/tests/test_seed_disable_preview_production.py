from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import initialize_database, reset_database_runtime, session_scope
from app.models.auth import AuthUser
from app.models.comments import CommentRecord
from app.models.market import MarketItemRecord
from app.models.materials import MaterialRecord
from app.models.requests import RequestRecord
from app.repos.auth_repo import AuthRepository
from app.repos.comment_repo import CommentRepository
from app.repos.market_repo import MarketRepository
from app.repos.material_catalog_repo import MaterialCatalogRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.repos.request_repo import RequestRepository
from app.services.market_service import MarketService
from app.services.materials_service import MaterialsService


def _reset_runtime_state() -> None:
    reset_database_runtime()
    get_settings.cache_clear()


def _write_private_env(root: Path, environment: str, content: str) -> Path:
    private_dir = root / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / f".env.{environment}").write_text(content.strip() + "\n", encoding="utf-8")
    return private_dir


def _configure_test_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "test")
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'seed-disable.sqlite3'}")
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")
    _reset_runtime_state()
    initialize_database()


def test_preview_disables_seed_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = _write_private_env(
        tmp_path,
        "preview",
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
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()
    settings = get_settings()

    read_repo = ReadApiRepository(settings.resolved_read_api_seed_path)
    catalog_repo = MaterialCatalogRepository(settings.resolved_material_column_seed_path)

    assert settings.seed_data_enabled is False
    assert read_repo.load_seed() == {}
    assert catalog_repo.load_seed() == {}

    _reset_runtime_state()


def test_production_disables_seed_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = _write_private_env(
        tmp_path,
        "production",
        """
        STUDYHUB_ENVIRONMENT=production
        STUDYHUB_DATABASE_URL=mysql+pymysql://prod_user:prod_pass@127.0.0.1:3306/studyhub_prod
        STUDYHUB_JWT_SECRET=prod-secret-abcdefghijklmnopqrstuvwxyz
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.prod.example.com
        STUDYHUB_SMTP_FROM_EMAIL=prod@example.com
        STUDYHUB_STORAGE_PROVIDER=oss
        STUDYHUB_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
        STUDYHUB_OSS_BUCKET=studyhub-prod
        STUDYHUB_OSS_ACCESS_KEY_ID=prod-ak
        STUDYHUB_OSS_ACCESS_KEY_SECRET=prod-sk
        STUDYHUB_PAYMENT_PROVIDER=alipay_page
        STUDYHUB_ALIPAY_APP_ID=2021000000000000
        STUDYHUB_ALIPAY_APP_PRIVATE_KEY_PATH=/root/StudyHub-FastAPI/private/mock-alipay-private.pem
        STUDYHUB_ALIPAY_PUBLIC_KEY_PATH=/root/StudyHub-FastAPI/private/mock-alipay-public.pem
        STUDYHUB_PAYOUT_TRANSFER_PROVIDER=alipay_transfer
        STUDYHUB_KYC_PROVIDER=aliyun_cloud_auth
        STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_ID=aliyun-ak
        STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_SECRET=aliyun-sk
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()
    settings = get_settings()

    read_repo = ReadApiRepository(settings.resolved_read_api_seed_path)
    catalog_repo = MaterialCatalogRepository(settings.resolved_material_column_seed_path)

    assert settings.seed_data_enabled is False
    assert read_repo.load_seed() == {}
    assert catalog_repo.load_seed() == {}

    _reset_runtime_state()


def test_disabled_seed_bootstrap_never_inserts_example_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_sqlite(tmp_path, monkeypatch)
    monkeypatch.setattr("app.repos.read_api_repo.get_settings", lambda: SimpleNamespace(seed_data_enabled=False))

    settings = get_settings()
    read_repo = ReadApiRepository(settings.resolved_read_api_seed_path)
    seed = read_repo.load_seed()

    with session_scope() as session:
        MaterialRepository().ensure_seed_bootstrap(session, seed)
        MarketRepository().ensure_seed_bootstrap(session, seed)
        RequestRepository().ensure_seed_bootstrap(session, seed)
        CommentRepository().ensure_seed_bootstrap(session, seed)

        assert seed == {}
        assert int(session.scalar(select(func.count()).select_from(MaterialRecord)) or 0) == 0
        assert int(session.scalar(select(func.count()).select_from(MarketItemRecord)) or 0) == 0
        assert int(session.scalar(select(func.count()).select_from(RequestRecord)) or 0) == 0
        assert int(session.scalar(select(func.count()).select_from(CommentRecord)) or 0) == 0

    _reset_runtime_state()


def test_materials_and_market_stats_use_real_user_count_when_seed_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_sqlite(tmp_path, monkeypatch)
    monkeypatch.setattr("app.repos.read_api_repo.get_settings", lambda: SimpleNamespace(seed_data_enabled=False))

    settings = get_settings()
    auth_repo = AuthRepository()
    read_repo = ReadApiRepository(settings.resolved_read_api_seed_path)

    with session_scope() as session:
        user = AuthUser(
            username="real_user",
            nickname="真实用户",
            email="real_user@example.com",
            password_hash="hashed",
        )
        auth_repo.save_user(session, user)
        user_id = user.id

        materials_service = MaterialsService(settings, read_repo, auth_repo, MaterialRepository(), asset_store=None)
        market_service = MarketService(read_repo, auth_repo, MarketRepository(), asset_store=None)

        materials_payload = materials_service.list_materials(
            session,
            current_user_id=user_id,
            keyword=None,
            school=None,
            college=None,
            major=None,
            tag=None,
            grade_value=None,
            course_category=None,
            price=None,
            sort="recommend",
            page=1,
            size=12,
        )
        market_payload = market_service.list_market(
            session,
            current_user_id=user_id,
            keyword=None,
            category=None,
            page=1,
            size=12,
        )

        assert materials_payload["stats"]["userCount"] == 1
        assert market_payload["stats"]["userCount"] == 1

    _reset_runtime_state()
