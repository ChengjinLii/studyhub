from __future__ import annotations

import os
from pathlib import Path
import subprocess
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config_validation import validate_runtime_configuration as validate_settings_runtime_configuration


BACKEND_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = BACKEND_ROOT.parent
DEFAULT_DEV_JWT_SECRET = "studyhub-fastapi-dev-secret-change-in-private-env-20260326"
DEFAULT_PRODUCTION_CSP_REPORT_ONLY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "connect-src 'self' https: wss:; "
    "form-action 'self' https://openapi.alipay.com https://openapi-sandbox.dl.alipaydev.com; "
    "report-uri /api/security/csp-reports"
)


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
    trusted_hosts: str | None = None
    trusted_proxy_ips: str | None = None
    docs_enabled: bool | None = None
    database_url: str | None = None
    database_auto_create: bool | None = None
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    database_echo: bool = False
    async_read_db_enabled: bool = True
    public_read_cache_enabled: bool = True
    public_read_cache_backend: str = "auto"
    public_read_cache_prefix: str = "public-read-cache"
    public_read_cache_ttl_seconds: int = 30
    public_read_cache_max_entries: int = 1024
    response_gzip_enabled: bool = True
    response_gzip_minimum_size_bytes: int = 1024
    response_gzip_compresslevel: int = 5
    mcp_enabled: bool | None = None
    mcp_allowed_origins: str | None = None
    mcp_require_auth: bool | None = None
    mcp_auth_mode: str = "static"
    mcp_access_token: str | None = None
    mcp_access_tokens: str | None = None
    mcp_read_scope: str = "studyhub.read"
    mcp_oauth_authorization_servers: str | None = None
    mcp_oauth_issuer: str | None = None
    mcp_oauth_jwks_uri: str | None = None
    mcp_oauth_audience: str | None = None
    mcp_oauth_algorithms: str = "RS256,ES256"
    mcp_resource_documentation_url: str | None = None
    mcp_client_rate_limit: int = 60
    mcp_client_quota: int = 1000
    mcp_client_quota_window_seconds: int = 86400
    ai_agent_provider: str = "local"
    ai_agent_base_url: str | None = None
    ai_agent_api_key: str | None = None
    ai_agent_model: str | None = None
    ai_agent_thinking_enabled: bool = False
    ai_agent_reasoning_effort: str = "none"
    ai_agent_timeout_seconds: float = 20.0
    ai_agent_max_output_tokens: int = 1800
    ai_agent_dynamic_tools_enabled: bool = False
    ai_agent_tool_max_rounds: int = 4
    ai_agent_tool_max_calls: int = 8
    ai_agent_tool_max_search_calls: int = 3
    ai_agent_tool_max_candidates: int = 18
    ai_agent_tool_max_evidence_pages: int = 12
    ai_agent_orchestrator_provider: str | None = None
    ai_agent_orchestrator_base_url: str | None = None
    ai_agent_orchestrator_api_key: str | None = None
    ai_agent_orchestrator_model: str = "deepseek-v4-flash"
    ai_agent_orchestrator_timeout_seconds: float = 8.0
    ai_agent_orchestrator_max_output_tokens: int = 1600
    ai_agent_validator_provider: str | None = None
    ai_agent_validator_base_url: str | None = None
    ai_agent_validator_api_key: str | None = None
    ai_agent_validator_model: str = "v4-flash"
    ai_agent_validator_timeout_seconds: float = 8.0
    ai_agent_max_context_materials: int = 6
    ai_agent_pdf_evidence_enabled: bool = True
    ai_agent_pdf_evidence_max_materials: int = 2
    ai_agent_pdf_evidence_max_pages: int = 6
    ai_agent_pdf_extract_max_pages: int = 80
    ai_agent_pdf_evidence_max_bytes: int = 4 * 1024 * 1024
    ai_agent_pdf_extract_cache_enabled: bool = True
    ai_agent_pdf_extract_cache_max_entries: int = 64
    ai_agent_memory_context_enabled: bool = True
    ai_agent_memory_max_materials: int = 8
    ai_agent_memory_max_interaction_checks: int = 6
    ai_agent_memory_cookie_name: str = "studyhub_ai_memory"
    ai_agent_session_memory_enabled: bool = True
    ai_agent_session_memory_ttl_seconds: int = 604800
    ai_agent_session_memory_max_turns: int = 12
    ai_agent_session_memory_max_context_chars: int = 6000
    ai_agent_session_memory_max_sessions: int = 1024
    agentic_platform_enabled: bool = False
    agentic_admin_only: bool = True
    agentic_runtime: str = "legacy"
    agentic_checkpointer: str = "sqlite"
    agentic_transition_export_enabled: bool = True
    # Proactive work is a separately activated Shadow Mode.  It never turns on
    # merely because the admin control plane is available.
    agentic_proactive_enabled: bool = False
    agentic_shadow_admin_actor_id: int | None = None
    agentic_worker_lock_name: str = "studyhub:agentic"
    agentic_worker_lock_timeout_seconds: int = 10
    agentic_worker_batch_size: int = 8
    agentic_worker_claim_ttl_seconds: int = 300
    agentic_worker_retry_delay_seconds: int = 60
    agentic_worker_max_attempts: int = 3
    # The generic execution plane is independently opt-in.  Keeping it
    # separate from proactive Shadow Mode prevents an admin control-plane
    # deploy from accidentally starting model-backed work.
    agentic_execution_enabled: bool = False
    agentic_execution_batch_size: int = 4
    agentic_execution_claim_ttl_seconds: int = 900
    agentic_execution_max_attempts: int = 3
    deep_research_enabled: bool = False
    deep_research_web_enabled: bool = False
    deep_research_scholar_enabled: bool = False
    deep_research_python_enabled: bool = False
    agentic_max_turns: int = 8
    agentic_max_skill_calls: int = 12
    deep_research_max_search_turns: int = 4
    deep_research_max_page_reads: int = 10
    agentic_max_context_tokens: int = 16000
    public_site_base_url: str = "https://study-hub.cn"
    security_headers_enabled: bool = True
    security_hsts_enabled: bool | None = None
    security_hsts_max_age_seconds: int = 15552000
    security_frame_options: str = "DENY"
    security_referrer_policy: str = "strict-origin-when-cross-origin"
    security_permissions_policy: str = "camera=(), microphone=(), geolocation=()"
    security_csp: str | None = None
    security_csp_report_only: str | None = None
    write_origin_protection_enabled: bool | None = None
    write_origin_require_header: bool | None = None
    trusted_site_origins: str | None = None
    rate_limit_enabled: bool = True
    rate_limit_backend: str = "auto"
    rate_limit_window_seconds: int = 60
    rate_limit_login: int = 1000
    rate_limit_captcha: int = 1000
    rate_limit_email_verification: int = 1000
    rate_limit_upload: int = 1000
    rate_limit_view: int = 1000
    rate_limit_mcp: int = 1000

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
    cookie_secure: bool | None = None
    auth_cookie_ttl_seconds: int = 86400
    remember_cookie_ttl_seconds: int = 604800
    auth_response_include_token: bool | None = None
    password_reset_hide_unknown_account: bool | None = None

    jwt_secret: str = DEFAULT_DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 86400
    bcrypt_rounds: int = 10

    captcha_backend: str = "auto"
    captcha_ttl_seconds: int = 60
    captcha_code_length: int = 4
    verification_ttl_seconds: int = 300
    verification_resend_after_seconds: int = 120
    verification_max_attempts: int = 5
    verification_code_length: int = 6

    default_role_mask: int = 1
    initial_download_quota: int = 200
    platform_commission_rate: float = 0.10
    request_commission_rate: float = 0.05
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
    material_file_max_size_bytes: int = 50 * 1024 * 1024
    material_preview_image_max_size_bytes: int = 5 * 1024 * 1024
    material_manual_preview_max_images: int = 10
    material_custom_preview_max_images: int = 5
    market_image_max_size_bytes: int = 5 * 1024 * 1024
    market_max_images: int = 3
    safe_image_mime_types: str = "image/png,image/jpeg,image/webp,image/gif,image/bmp,image/avif,image/heic,image/heif"
    safe_image_extensions: str = ".png,.jpg,.jpeg,.webp,.gif,.bmp,.avif,.heic,.heif"

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

    @staticmethod
    def _split_csv(value: str | None) -> list[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

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
        return self._split_csv(self.cors_allowed_origins)

    @property
    def resolved_cors_allow_origin_regex(self) -> str | None:
        if self.cors_allow_origin_regex:
            return self.cors_allow_origin_regex
        if self.environment.strip().lower() in {"local-dev", "test"}:
            return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
        return None

    @property
    def resolved_mcp_allowed_origins(self) -> list[str]:
        return self._split_csv(self.mcp_allowed_origins)

    @property
    def resolved_mcp_enabled(self) -> bool:
        if self.mcp_enabled is not None:
            return bool(self.mcp_enabled)
        return not (self.is_preview or self.is_production)

    @property
    def resolved_mcp_require_auth(self) -> bool:
        if self.mcp_require_auth is not None:
            return bool(self.mcp_require_auth)
        return self.is_preview or self.is_production

    @property
    def resolved_mcp_auth_mode(self) -> str:
        return (self.mcp_auth_mode or "static").strip().lower()

    @property
    def resolved_mcp_oauth_authorization_servers(self) -> list[str]:
        return self._split_csv(self.mcp_oauth_authorization_servers)

    @property
    def resolved_mcp_oauth_algorithms(self) -> list[str]:
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
        return [item for item in self._split_csv(self.mcp_oauth_algorithms) if item in allowed] or ["RS256", "ES256"]

    @property
    def resolved_mcp_oauth_audience(self) -> str:
        return (self.mcp_oauth_audience or f"{self.resolved_public_site_base_url}/mcp").strip()

    @property
    def resolved_mcp_resource_documentation_url(self) -> str:
        return (
            self.mcp_resource_documentation_url
            or "https://github.com/ChengjinLii/studyhub/blob/main/MCP.md"
        ).strip()

    @property
    def resolved_docs_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return bool(self.docs_enabled)
        return not (self.is_preview or self.is_production)

    @property
    def resolved_openapi_url(self) -> str | None:
        return "/openapi.json" if self.resolved_docs_enabled else None

    @property
    def resolved_docs_url(self) -> str | None:
        return "/docs" if self.resolved_docs_enabled else None

    @property
    def resolved_redoc_url(self) -> str | None:
        return "/redoc" if self.resolved_docs_enabled else None

    @property
    def resolved_trusted_hosts(self) -> list[str]:
        return self._split_csv(self.trusted_hosts)

    @property
    def resolved_trusted_proxy_ips(self) -> list[str]:
        configured = self._split_csv(self.trusted_proxy_ips)
        if configured:
            return configured
        return ["127.0.0.1", "::1"]

    @property
    def resolved_public_site_base_url(self) -> str:
        return self.public_site_base_url.rstrip("/")

    @property
    def resolved_security_hsts_enabled(self) -> bool:
        if self.security_hsts_enabled is not None:
            return bool(self.security_hsts_enabled)
        return self.is_preview or self.is_production

    @property
    def resolved_write_origin_protection_enabled(self) -> bool:
        if self.write_origin_protection_enabled is not None:
            return bool(self.write_origin_protection_enabled)
        return self.is_preview or self.is_production

    @property
    def resolved_write_origin_require_header(self) -> bool:
        if self.write_origin_require_header is not None:
            return bool(self.write_origin_require_header)
        return self.is_preview or self.is_production

    @property
    def resolved_trusted_site_origins(self) -> set[str]:
        origins = set(self.resolved_cors_allowed_origins)
        if self.trusted_site_origins:
            origins.update(self._split_csv(self.trusted_site_origins))
        public_base = self.resolved_public_site_base_url
        if public_base:
            origins.add(public_base)
        if self.environment.strip().lower() in {"local-dev", "test"}:
            origins.update({"http://localhost:3000", "http://127.0.0.1:3000", "http://testserver"})
        return origins

    @property
    def resolved_cookie_secure(self) -> bool:
        if self.cookie_secure is not None:
            return bool(self.cookie_secure)
        return self.is_preview or self.is_production

    @property
    def resolved_auth_response_include_token(self) -> bool:
        if self.auth_response_include_token is not None:
            return bool(self.auth_response_include_token)
        return not (self.is_preview or self.is_production)

    @property
    def resolved_security_csp_report_only(self) -> str | None:
        if self.security_csp_report_only:
            return self.security_csp_report_only
        if self.is_preview or self.is_production:
            return DEFAULT_PRODUCTION_CSP_REPORT_ONLY
        return None

    @property
    def resolved_password_reset_hide_unknown_account(self) -> bool:
        if self.password_reset_hide_unknown_account is not None:
            return bool(self.password_reset_hide_unknown_account)
        return self.is_preview or self.is_production

    @property
    def resolved_safe_image_mime_types(self) -> set[str]:
        raw = self.safe_image_mime_types or ""
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    @property
    def resolved_safe_image_extensions(self) -> set[str]:
        raw = self.safe_image_extensions or ""
        normalized: set[str] = set()
        for item in raw.split(","):
            value = item.strip().lower()
            if not value:
                continue
            normalized.add(value if value.startswith(".") else f".{value}")
        return normalized

    def validate_runtime_configuration(self) -> None:
        validate_settings_runtime_configuration(self, default_dev_jwt_secret=DEFAULT_DEV_JWT_SECRET)


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
