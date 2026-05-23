from __future__ import annotations

from typing import Any


LOCAL_MAIL_PROVIDERS = {"local_outbox"}
LOCAL_STORAGE_PROVIDERS = {"local_fs"}
LOCAL_PAYMENT_PROVIDERS = {"local_alipay"}
LOCAL_KYC_PROVIDERS = {"mock_local"}
LOCAL_LOCK_PROVIDERS = {"db_row"}
LOCAL_TRANSFER_PROVIDERS = {"local_transfer"}


def validate_runtime_configuration(settings: Any, *, default_dev_jwt_secret: str) -> None:
    if settings.log_format not in {"text", "json"}:
        raise RuntimeError("STUDYHUB_LOG_FORMAT 只允许为 text 或 json。")
    if settings.requires_private_env_file:
        env_file = settings.private_env_file
        if env_file is None or not env_file.exists():
            raise RuntimeError(
                f"{settings.environment} 模式要求 private 环境文件存在：{settings.private_dir / f'.env.{settings.environment.strip().lower()}'}"
            )
        if settings.resolved_database_url.startswith("sqlite"):
            raise RuntimeError(f"{settings.environment} 模式禁止使用 SQLite，请改为真实 MySQL 连接。")
        if settings.jwt_secret == default_dev_jwt_secret:
            raise RuntimeError(f"{settings.environment} 模式禁止使用默认 JWT 密钥，请在 private 环境文件中覆盖。")
        if settings.is_production and settings.should_auto_create_database:
            raise RuntimeError("production 模式禁止自动创建数据库 schema，请改用显式迁移脚本。")

    _validate_storage(settings)
    _validate_mail(settings)
    _validate_lock(settings)
    _validate_payment(settings)
    _validate_kyc(settings)
    _validate_production_providers(settings)


def _validate_storage(settings: Any) -> None:
    if settings.storage_provider != "oss":
        return
    missing_keys: list[str] = []
    if not settings.oss_endpoint:
        missing_keys.append("STUDYHUB_OSS_ENDPOINT")
    if not settings.oss_bucket:
        missing_keys.append("STUDYHUB_OSS_BUCKET")
    if not settings.oss_access_key_id:
        missing_keys.append("STUDYHUB_OSS_ACCESS_KEY_ID")
    if not settings.oss_access_key_secret:
        missing_keys.append("STUDYHUB_OSS_ACCESS_KEY_SECRET")
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise RuntimeError(f"OSS provider 缺少必要配置：{missing}")


def _validate_mail(settings: Any) -> None:
    if settings.mail_provider != "smtp":
        return
    missing_keys: list[str] = []
    if not settings.smtp_host:
        missing_keys.append("STUDYHUB_SMTP_HOST")
    if not settings.smtp_from_email:
        missing_keys.append("STUDYHUB_SMTP_FROM_EMAIL")
    if settings.smtp_username and not settings.smtp_password:
        missing_keys.append("STUDYHUB_SMTP_PASSWORD")
    if settings.smtp_use_ssl and settings.smtp_starttls:
        raise RuntimeError("SMTP 配置非法：不能同时启用 SSL 和 STARTTLS。")
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise RuntimeError(f"SMTP provider 缺少必要配置：{missing}")


def _validate_lock(settings: Any) -> None:
    if settings.lock_provider == "redis" and not settings.redis_url:
        raise RuntimeError("Redis lock provider 缺少 STUDYHUB_REDIS_URL 配置。")


def _validate_payment(settings: Any) -> None:
    if settings.payment_provider != "alipay_page" and settings.payout_transfer_provider != "alipay_transfer":
        return
    missing_keys: list[str] = []
    if not settings.alipay_app_id:
        missing_keys.append("STUDYHUB_ALIPAY_APP_ID")
    if not settings.alipay_app_private_key_path:
        missing_keys.append("STUDYHUB_ALIPAY_APP_PRIVATE_KEY_PATH")
    if not settings.alipay_public_key_path and not settings.alipay_public_cert_path:
        missing_keys.append("STUDYHUB_ALIPAY_PUBLIC_KEY_PATH or STUDYHUB_ALIPAY_PUBLIC_CERT_PATH")
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise RuntimeError(f"Alipay provider 缺少必要配置：{missing}")


def _validate_kyc(settings: Any) -> None:
    if settings.kyc_provider != "aliyun_cloud_auth":
        return
    missing_keys: list[str] = []
    if not settings.alibaba_cloud_access_key_id:
        missing_keys.append("STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_ID")
    if not settings.alibaba_cloud_access_key_secret:
        missing_keys.append("STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise RuntimeError(f"KYC provider 缺少必要配置：{missing}")


def _validate_production_providers(settings: Any) -> None:
    if not settings.is_production:
        return
    if settings.mail_provider in LOCAL_MAIL_PROVIDERS:
        raise RuntimeError("production 模式禁止使用 local_outbox 邮件 provider。")
    if settings.storage_provider in LOCAL_STORAGE_PROVIDERS:
        raise RuntimeError("production 模式禁止使用 local_fs 存储 provider。")
    if settings.payment_provider in LOCAL_PAYMENT_PROVIDERS:
        raise RuntimeError("production 模式禁止使用 local_alipay 支付 provider。")
    if settings.kyc_provider in LOCAL_KYC_PROVIDERS:
        raise RuntimeError("production 模式禁止使用 mock_local KYC provider。")
    if settings.payout_transfer_provider in LOCAL_TRANSFER_PROVIDERS:
        raise RuntimeError("production 模式禁止使用 local_transfer 提现 provider。")
