from __future__ import annotations

import os
from pathlib import Path
import subprocess
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = BACKEND_ROOT.parent
DEFAULT_DEV_JWT_SECRET = "studyhub-fastapi-dev-secret-change-in-private-env-20260326"
LOCAL_MAIL_PROVIDERS = {"local_outbox"}
LOCAL_STORAGE_PROVIDERS = {"local_fs"}
LOCAL_PAYMENT_PROVIDERS = {"local_alipay"}
LOCAL_KYC_PROVIDERS = {"mock_local"}
LOCAL_LOCK_PROVIDERS = {"db_row"}
LOCAL_TRANSFER_PROVIDERS = {"local_transfer"}


class Settings(BaseSettings):
    app_name: str = "StudyHub FastAPI"
    environment: str = "local-dev"
    api_prefix: str = "/api"
    host: str = "127.0.0.1"
    port: int = 8011
    log_level: str = "INFO"
    log_format: str = "text"
    access_log_enabled: bool = True
    access_log_skip_paths: str = "/api/healthz,/api/readyz,/api/metrics"
    build_git_sha: str | None = None
    local_dev_root_dir: str | None = None
    private_dir_path: str | None = None
    local_dev_bootstrap_user: bool = True
    local_dev_quick_login_enabled: bool = True
    local_dev_user_id: int = 900001
    local_dev_username: str = "developer"
    local_dev_password: str = "developer123"
    local_dev_nickname: str = "开发者"
    local_dev_email: str | None = "developer@local.studyhub.dev"
    local_dev_role_mask: int = 1
    local_dev_verified: bool = True
    mail_provider: str = "local_outbox"
    storage_provider: str = "local_fs"
    payment_provider: str = "local_alipay"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 15
    cors_allowed_origins: str | None = None
    cors_allow_origin_regex: str | None = None
    database_url: str | None = None
    database_auto_create: bool | None = None
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    database_echo: bool = False
    public_read_cache_enabled: bool = True
    public_read_cache_backend: str = "auto"
    public_read_cache_prefix: str = "public-read-cache"
    public_read_cache_ttl_seconds: int = 5
    public_read_cache_max_entries: int = 256
    response_gzip_enabled: bool = True
    response_gzip_minimum_size_bytes: int = 1024
    response_gzip_compresslevel: int = 5

    lock_provider: str = "db_row"
    redis_url: str | None = None
    redis_namespace: str = "studyhub-fastapi"
    redis_lock_key_prefix: str = "locks"
    redis_socket_timeout_seconds: int = 5
    redis_connect_timeout_seconds: int = 5

    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_public_base_url: str | None = None
    oss_key_prefix: str = "studyhub-fastapi"

    alipay_env: str = "sandbox"
    alipay_app_id: str | None = None
    alipay_seller_id: str | None = None
    alipay_notify_url: str | None = None
    alipay_return_url: str | None = None
    alipay_app_private_key_path: str | None = None
    alipay_public_key_path: str | None = None
    alipay_app_cert_path: str | None = None
    alipay_public_cert_path: str | None = None
    alipay_root_cert_path: str | None = None
    alipay_sign_type: str = "RSA2"
    alipay_charset: str = "utf-8"

    payout_transfer_provider: str = "local_transfer"

    kyc_provider: str = "mock_local"
    kyc_enabled: bool = False
    kyc_region_id: str = "cn-shanghai"
    kyc_endpoint: str = "cloudauth.aliyuncs.com"
    kyc_api_version: str = "2022-03-30"
    alibaba_cloud_access_key_id: str | None = None
    alibaba_cloud_access_key_secret: str | None = None
    kyc_encryption_key: str | None = None
    kyc_hash_salt: str | None = None

    contract_sample_dir: str | None = None
    contract_report_dir: str | None = None
    material_column_seed_path: str | None = None
    read_api_seed_path: str | None = None
    material_asset_dir: str | None = None
    market_asset_dir: str | None = None
    payout_qr_asset_dir: str | None = None
    mail_outbox_dir: str | None = None

    cookie_token_name: str = "studyhub_token"
    cookie_user_name: str = "studyhub_user"
    cookie_same_site: str = "Lax"
    cookie_path: str = "/"
    auth_cookie_ttl_seconds: int = 86400
    remember_cookie_ttl_seconds: int = 604800

    jwt_secret: str = DEFAULT_DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 86400
    bcrypt_rounds: int = 10

    captcha_ttl_seconds: int = 60
    captcha_code_length: int = 4
    verification_ttl_seconds: int = 300
    verification_resend_after_seconds: int = 120
    verification_max_attempts: int = 5
    verification_code_length: int = 6

    default_role_mask: int = 1
    initial_download_quota: int = 200
    platform_commission_rate: float = 0.30
    settlement_payout_delay_days: int = 7
    settlement_policy_version: str = "MARKET_FASTAPI_V1"
    payout_min_amount_cents: int = 1000
    payout_transfer_lock_name: str = "studyhub:payout:transfer-query"
    payout_transfer_lock_timeout_seconds: int = 2
    settlement_lock_name: str = "studyhub:settlement"
    settlement_lock_timeout_seconds: int = 2
    request_refund_lock_name: str = "studyhub:request-refund"
    request_refund_lock_timeout_seconds: int = 2
    worker_lock_ttl_seconds: int = 120
    kyc_reuse_days: int = 365
    kyc_retry_cooldown_seconds: int = 60
    kyc_max_attempts_per_day: int = 2
    payout_qr_max_size_bytes: int = 5 * 1024 * 1024

    default_column_topic: str = "experience"
    default_column_page_size: int = 12
    max_column_page_size: int = 24
    column_cache_control: str = "public, max-age=45, must-revalidate"
    material_signed_url_ttl_seconds: int = 900
    material_preview_pages_small: int = 3
    material_preview_pages_large: int = 5

    model_config = SettingsConfigDict(
        env_prefix="STUDYHUB_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def backend_root(self) -> Path:
        return BACKEND_ROOT

    @property
    def stack_root(self) -> Path:
        return STACK_ROOT

    @property
    def project_root(self) -> Path:
        return self.backend_root

    @property
    def resolved_build_git_sha(self) -> str:
        if self.build_git_sha:
            return self.build_git_sha
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.stack_root), "rev-parse", "--short", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            git_sha = completed.stdout.strip()
            if git_sha:
                return git_sha
        except Exception:
            pass
        return "local-dev"

    @property
    def resolved_access_log_skip_paths(self) -> set[str]:
        raw = self.access_log_skip_paths or ""
        return {item.strip() for item in raw.split(",") if item.strip()}

    @property
    def private_dir(self) -> Path:
        if self.private_dir_path:
            return Path(self.private_dir_path)
        return self.stack_root / "private"

    @property
    def is_local_dev(self) -> bool:
        return self.environment.strip().lower() == "local-dev"

    @property
    def is_preview(self) -> bool:
        return self.environment.strip().lower() == "preview"

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def seed_data_enabled(self) -> bool:
        return not (self.is_preview or self.is_production)

    @property
    def requires_private_env_file(self) -> bool:
        return self.is_preview or self.is_production

    @property
    def allows_partial_schema_compatibility(self) -> bool:
        return self.is_preview

    @property
    def private_env_file(self) -> Path | None:
        if not self.requires_private_env_file:
            return None
        return self.private_dir / f".env.{self.environment.strip().lower()}"

    @property
    def local_dev_root(self) -> Path:
        if self.local_dev_root_dir:
            return Path(self.local_dev_root_dir)
        return self.stack_root / ".local-dev"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        runtime_root = self.local_dev_root if self.is_local_dev else self.private_dir
        sqlite_path = runtime_root / "studyhub_fastapi.sqlite3"
        return f"sqlite+pysqlite:///{sqlite_path}"

    @property
    def database_is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def should_auto_create_database(self) -> bool:
        if self.database_auto_create is not None:
            return bool(self.database_auto_create)
        return not self.requires_private_env_file

    @property
    def resolved_contract_sample_dir(self) -> Path:
        if self.contract_sample_dir:
            return Path(self.contract_sample_dir)
        return self.backend_root / "fixtures" / "contracts"

    @property
    def resolved_contract_report_dir(self) -> Path:
        if self.contract_report_dir:
            return Path(self.contract_report_dir)
        return self.backend_root / "artifacts" / "contract-diff"

    @property
    def resolved_material_column_seed_path(self) -> Path:
        if self.material_column_seed_path:
            return Path(self.material_column_seed_path)
        return self.backend_root / "fixtures" / "runtime" / "materials_column_seed.json"

    @property
    def resolved_read_api_seed_path(self) -> Path:
        if self.read_api_seed_path:
            return Path(self.read_api_seed_path)
        return self.backend_root / "fixtures" / "runtime" / "read_api_seed.json"

    @property
    def resolved_material_asset_dir(self) -> Path:
        if self.material_asset_dir:
            return Path(self.material_asset_dir)
        runtime_root = self.local_dev_root if self.is_local_dev else self.private_dir
        return runtime_root / "materials"

    @property
    def resolved_market_asset_dir(self) -> Path:
        if self.market_asset_dir:
            return Path(self.market_asset_dir)
        runtime_root = self.local_dev_root if self.is_local_dev else self.private_dir
        return runtime_root / "market"

    @property
    def resolved_payout_qr_asset_dir(self) -> Path:
        if self.payout_qr_asset_dir:
            return Path(self.payout_qr_asset_dir)
        runtime_root = self.local_dev_root if self.is_local_dev else self.private_dir
        return runtime_root / "payout-qr"

    @property
    def resolved_mail_outbox_dir(self) -> Path:
        if self.mail_outbox_dir:
            return Path(self.mail_outbox_dir)
        runtime_root = self.local_dev_root if self.is_local_dev else self.private_dir
        return runtime_root / "outbox" / "mail"

    @property
    def resolved_cors_allowed_origins(self) -> list[str]:
        if not self.cors_allowed_origins:
            return []
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def resolved_cors_allow_origin_regex(self) -> str | None:
        if self.cors_allow_origin_regex:
            return self.cors_allow_origin_regex
        if self.environment.strip().lower() in {"local-dev", "test"}:
            return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
        return None

    def validate_runtime_configuration(self) -> None:
        if self.log_format not in {"text", "json"}:
            raise RuntimeError("STUDYHUB_LOG_FORMAT 只允许为 text 或 json。")
        if self.requires_private_env_file:
            env_file = self.private_env_file
            if env_file is None or not env_file.exists():
                raise RuntimeError(
                    f"{self.environment} 模式要求 private 环境文件存在：{self.private_dir / f'.env.{self.environment.strip().lower()}'}"
                )
            if self.resolved_database_url.startswith("sqlite"):
                raise RuntimeError(f"{self.environment} 模式禁止使用 SQLite，请改为真实 MySQL 连接。")
            if self.jwt_secret == DEFAULT_DEV_JWT_SECRET:
                raise RuntimeError(f"{self.environment} 模式禁止使用默认 JWT 密钥，请在 private 环境文件中覆盖。")
            if self.is_production and self.should_auto_create_database:
                raise RuntimeError("production 模式禁止自动创建数据库 schema，请改用显式迁移脚本。")

        if self.storage_provider == "oss":
            missing_keys: list[str] = []
            if not self.oss_endpoint:
                missing_keys.append("STUDYHUB_OSS_ENDPOINT")
            if not self.oss_bucket:
                missing_keys.append("STUDYHUB_OSS_BUCKET")
            if not self.oss_access_key_id:
                missing_keys.append("STUDYHUB_OSS_ACCESS_KEY_ID")
            if not self.oss_access_key_secret:
                missing_keys.append("STUDYHUB_OSS_ACCESS_KEY_SECRET")
            if missing_keys:
                missing = ", ".join(missing_keys)
                raise RuntimeError(f"OSS provider 缺少必要配置：{missing}")

        if self.mail_provider == "smtp":
            missing_keys: list[str] = []
            if not self.smtp_host:
                missing_keys.append("STUDYHUB_SMTP_HOST")
            if not self.smtp_from_email:
                missing_keys.append("STUDYHUB_SMTP_FROM_EMAIL")
            if self.smtp_username and not self.smtp_password:
                missing_keys.append("STUDYHUB_SMTP_PASSWORD")
            if self.smtp_use_ssl and self.smtp_starttls:
                raise RuntimeError("SMTP 配置非法：不能同时启用 SSL 和 STARTTLS。")
            if missing_keys:
                missing = ", ".join(missing_keys)
                raise RuntimeError(f"SMTP provider 缺少必要配置：{missing}")

        if self.lock_provider == "redis" and not self.redis_url:
            raise RuntimeError("Redis lock provider 缺少 STUDYHUB_REDIS_URL 配置。")

        if self.payment_provider == "alipay_page" or self.payout_transfer_provider == "alipay_transfer":
            missing_keys: list[str] = []
            if not self.alipay_app_id:
                missing_keys.append("STUDYHUB_ALIPAY_APP_ID")
            if not self.alipay_app_private_key_path:
                missing_keys.append("STUDYHUB_ALIPAY_APP_PRIVATE_KEY_PATH")
            if not self.alipay_public_key_path and not self.alipay_public_cert_path:
                missing_keys.append("STUDYHUB_ALIPAY_PUBLIC_KEY_PATH or STUDYHUB_ALIPAY_PUBLIC_CERT_PATH")
            if missing_keys:
                missing = ", ".join(missing_keys)
                raise RuntimeError(f"Alipay provider 缺少必要配置：{missing}")

        if self.kyc_provider == "aliyun_cloud_auth":
            missing_keys: list[str] = []
            if not self.alibaba_cloud_access_key_id:
                missing_keys.append("STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_ID")
            if not self.alibaba_cloud_access_key_secret:
                missing_keys.append("STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_SECRET")
            if missing_keys:
                missing = ", ".join(missing_keys)
                raise RuntimeError(f"KYC provider 缺少必要配置：{missing}")

        if self.is_production:
            if self.mail_provider in LOCAL_MAIL_PROVIDERS:
                raise RuntimeError("production 模式禁止使用 local_outbox 邮件 provider。")
            if self.storage_provider in LOCAL_STORAGE_PROVIDERS:
                raise RuntimeError("production 模式禁止使用 local_fs 存储 provider。")
            if self.payment_provider in LOCAL_PAYMENT_PROVIDERS:
                raise RuntimeError("production 模式禁止使用 local_alipay 支付 provider。")
            if self.kyc_provider in LOCAL_KYC_PROVIDERS:
                raise RuntimeError("production 模式禁止使用 mock_local KYC provider。")
            if self.payout_transfer_provider in LOCAL_TRANSFER_PROVIDERS:
                raise RuntimeError("production 模式禁止使用 local_transfer 提现 provider。")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw_environment = os.getenv("STUDYHUB_ENVIRONMENT", "local-dev").strip().lower()
    raw_private_dir = os.getenv("STUDYHUB_PRIVATE_DIR_PATH")
    private_dir = Path(raw_private_dir) if raw_private_dir else STACK_ROOT / "private"

    if raw_environment in {"preview", "production"}:
        env_file = private_dir / f".env.{raw_environment}"
        settings = Settings(_env_file=env_file if env_file.exists() else None)
    else:
        settings = Settings()

    settings.validate_runtime_configuration()
    return settings
