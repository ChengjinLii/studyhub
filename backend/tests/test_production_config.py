from __future__ import annotations

from pathlib import Path

import pytest

from app.api.deps import (
    clear_dependency_caches,
    get_kyc_provider,
    get_lock_provider,
    get_mail_provider,
    get_payment_provider,
    get_storage_provider,
    get_transfer_provider,
)
from app.core.config import get_settings
from app.core.db import reset_database_runtime
from app.providers.kyc import AliyunCloudAuthKycProvider
from app.providers.lock import RedisLockProvider
from app.providers.mail import SmtpMailProvider
from app.providers.payment import AlipayPagePaymentProvider
from app.providers.storage import AliyunOssStorageProvider
from app.providers.transfer import AlipayTransferProvider


def _reset_runtime_state() -> None:
    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()


def _write_private_env(
    root: Path,
    environment: str,
    content: str,
) -> Path:
    private_dir = root / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    target = private_dir / f".env.{environment}"
    target.write_text(content.strip() + "\n", encoding="utf-8")
    return private_dir


def test_preview_requires_private_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(tmp_path / "private"))

    _reset_runtime_state()

    with pytest.raises(RuntimeError, match="private 环境文件存在"):
        get_settings()

    _reset_runtime_state()


def test_preview_loads_private_env_and_supports_smtp_provider(
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
        STUDYHUB_SMTP_PORT=587
        STUDYHUB_SMTP_FROM_EMAIL=preview@example.com
        STUDYHUB_SMTP_STARTTLS=true
        STUDYHUB_STORAGE_PROVIDER=local_fs
        STUDYHUB_PAYMENT_PROVIDER=local_alipay
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()

    settings = get_settings()
    provider = get_mail_provider()

    assert settings.is_preview is True
    assert settings.private_env_file == private_dir / ".env.preview"
    assert settings.resolved_database_url.startswith("mysql+pymysql://")
    assert settings.mail_provider == "smtp"
    assert isinstance(provider, SmtpMailProvider)

    _reset_runtime_state()


def test_preview_supports_real_provider_selection_without_touching_network(
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
        STUDYHUB_SMTP_PORT=587
        STUDYHUB_SMTP_FROM_EMAIL=preview@example.com
        STUDYHUB_SMTP_STARTTLS=true
        STUDYHUB_STORAGE_PROVIDER=oss
        STUDYHUB_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
        STUDYHUB_OSS_BUCKET=studyhub-preview
        STUDYHUB_OSS_ACCESS_KEY_ID=preview-ak
        STUDYHUB_OSS_ACCESS_KEY_SECRET=preview-sk
        STUDYHUB_LOCK_PROVIDER=redis
        STUDYHUB_REDIS_URL=redis://127.0.0.1:6379/8
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
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()

    assert isinstance(get_storage_provider(), AliyunOssStorageProvider)
    assert isinstance(get_lock_provider(), RedisLockProvider)
    assert isinstance(get_payment_provider(), AlipayPagePaymentProvider)
    assert isinstance(get_transfer_provider(), AlipayTransferProvider)
    assert isinstance(get_kyc_provider(), AliyunCloudAuthKycProvider)

    _reset_runtime_state()


def test_preview_accepts_alipay_public_cert_path_without_public_key_path(
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
        STUDYHUB_SMTP_PORT=587
        STUDYHUB_SMTP_FROM_EMAIL=preview@example.com
        STUDYHUB_SMTP_STARTTLS=true
        STUDYHUB_STORAGE_PROVIDER=oss
        STUDYHUB_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
        STUDYHUB_OSS_BUCKET=studyhub-preview
        STUDYHUB_OSS_ACCESS_KEY_ID=preview-ak
        STUDYHUB_OSS_ACCESS_KEY_SECRET=preview-sk
        STUDYHUB_LOCK_PROVIDER=redis
        STUDYHUB_REDIS_URL=redis://127.0.0.1:6379/8
        STUDYHUB_PAYMENT_PROVIDER=alipay_page
        STUDYHUB_ALIPAY_APP_ID=2021000000000000
        STUDYHUB_ALIPAY_APP_PRIVATE_KEY_PATH=/root/StudyHub-FastAPI/private/mock-alipay-private.pem
        STUDYHUB_ALIPAY_PUBLIC_CERT_PATH=/root/StudyHub-FastAPI/private/mock-alipay-public.crt
        STUDYHUB_PAYOUT_TRANSFER_PROVIDER=alipay_transfer
        STUDYHUB_KYC_PROVIDER=aliyun_cloud_auth
        STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_ID=aliyun-ak
        STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_SECRET=aliyun-sk
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()

    settings = get_settings()
    assert settings.alipay_public_key_path is None
    assert settings.alipay_public_cert_path == "/root/StudyHub-FastAPI/private/mock-alipay-public.crt"
    assert isinstance(get_payment_provider(), AlipayPagePaymentProvider)

    _reset_runtime_state()


def test_production_rejects_default_jwt_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_dir = _write_private_env(
        tmp_path,
        "production",
        """
        STUDYHUB_ENVIRONMENT=production
        STUDYHUB_DATABASE_URL=mysql+pymysql://prod_user:prod_pass@127.0.0.1:3306/studyhub_prod
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.prod.example.com
        STUDYHUB_SMTP_PORT=465
        STUDYHUB_SMTP_FROM_EMAIL=noreply@example.com
        STUDYHUB_SMTP_USE_SSL=true
        STUDYHUB_SMTP_STARTTLS=false
        STUDYHUB_STORAGE_PROVIDER=oss
        STUDYHUB_PAYMENT_PROVIDER=alipay
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()

    with pytest.raises(RuntimeError, match="默认 JWT 密钥"):
        get_settings()

    _reset_runtime_state()


def test_production_rejects_sqlite_even_with_private_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = _write_private_env(
        tmp_path,
        "production",
        """
        STUDYHUB_ENVIRONMENT=production
        STUDYHUB_DATABASE_URL=sqlite+pysqlite:////tmp/studyhub-prod.sqlite3
        STUDYHUB_JWT_SECRET=prod-secret-abcdefghijklmnopqrstuvwxyz
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.prod.example.com
        STUDYHUB_SMTP_PORT=465
        STUDYHUB_SMTP_FROM_EMAIL=noreply@example.com
        STUDYHUB_SMTP_USE_SSL=true
        STUDYHUB_SMTP_STARTTLS=false
        STUDYHUB_STORAGE_PROVIDER=oss
        STUDYHUB_PAYMENT_PROVIDER=alipay
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()

    with pytest.raises(RuntimeError, match="禁止使用 SQLite"):
        get_settings()

    _reset_runtime_state()


def test_production_rejects_local_storage_and_payment_providers(
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
        STUDYHUB_SMTP_PORT=587
        STUDYHUB_SMTP_FROM_EMAIL=noreply@example.com
        STUDYHUB_SMTP_STARTTLS=true
        STUDYHUB_STORAGE_PROVIDER=local_fs
        STUDYHUB_PAYMENT_PROVIDER=local_alipay
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()

    with pytest.raises(RuntimeError, match="local_fs"):
        get_settings()

    _reset_runtime_state()


def test_production_allows_db_row_lock_but_rejects_local_kyc_and_transfer_providers(
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
        STUDYHUB_SMTP_PORT=587
        STUDYHUB_SMTP_FROM_EMAIL=noreply@example.com
        STUDYHUB_SMTP_STARTTLS=true
        STUDYHUB_STORAGE_PROVIDER=oss
        STUDYHUB_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
        STUDYHUB_OSS_BUCKET=studyhub-prod
        STUDYHUB_OSS_ACCESS_KEY_ID=prod-ak
        STUDYHUB_OSS_ACCESS_KEY_SECRET=prod-sk
        STUDYHUB_PAYMENT_PROVIDER=alipay_page
        STUDYHUB_ALIPAY_APP_ID=2021000000000000
        STUDYHUB_ALIPAY_APP_PRIVATE_KEY_PATH=/root/StudyHub-FastAPI/private/mock-alipay-private.pem
        STUDYHUB_ALIPAY_PUBLIC_KEY_PATH=/root/StudyHub-FastAPI/private/mock-alipay-public.pem
        STUDYHUB_LOCK_PROVIDER=db_row
        STUDYHUB_KYC_PROVIDER=mock_local
        STUDYHUB_PAYOUT_TRANSFER_PROVIDER=local_transfer
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()

    with pytest.raises(RuntimeError, match="mock_local"):
        get_settings()

    _reset_runtime_state()
