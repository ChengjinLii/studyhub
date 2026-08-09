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
    _validate_redis(settings)
    _validate_lock(settings)
    _validate_payment(settings)
    _validate_kyc(settings)
    _validate_mcp(settings)
    _validate_agentic_platform(settings)
    _validate_production_providers(settings)


def _validate_redis(settings: Any) -> None:
    backend_fields = {
        "STUDYHUB_RATE_LIMIT_BACKEND": settings.rate_limit_backend,
        "STUDYHUB_CAPTCHA_BACKEND": settings.captcha_backend,
        "STUDYHUB_SECURITY_STATE_BACKEND": settings.security_state_backend,
        "STUDYHUB_PUBLIC_READ_CACHE_BACKEND": settings.public_read_cache_backend,
    }
    for variable, raw_value in backend_fields.items():
        if str(raw_value or "auto").strip().lower() not in {"auto", "local", "redis"}:
            raise RuntimeError(f"{variable} 只允许为 auto、local 或 redis。")
    if float(settings.redis_socket_timeout_seconds) <= 0 or float(settings.redis_connect_timeout_seconds) <= 0:
        raise RuntimeError("Redis 连接与读取超时必须大于 0 秒。")
    explicitly_redis = any(str(value or "").strip().lower() == "redis" for value in backend_fields.values())
    if explicitly_redis and not settings.redis_url:
        raise RuntimeError("Redis 状态服务缺少 STUDYHUB_REDIS_URL 配置。")
    if settings.resolved_upload_authorization_required and not settings.redis_url and (
        settings.is_preview or settings.is_production
    ):
        raise RuntimeError("启用上传授权时必须配置 STUDYHUB_REDIS_URL。")
    if settings.is_preview or settings.is_production:
        required_redis_backends = {
            "STUDYHUB_RATE_LIMIT_BACKEND": settings.rate_limit_backend,
            "STUDYHUB_CAPTCHA_BACKEND": settings.captcha_backend,
            "STUDYHUB_SECURITY_STATE_BACKEND": settings.security_state_backend,
        }
        for variable, raw_value in required_redis_backends.items():
            resolved = "redis" if str(raw_value or "auto").strip().lower() == "auto" and settings.redis_url else str(raw_value).strip().lower()
            if resolved != "redis":
                raise RuntimeError(f"preview/production 的 {variable} 必须使用 redis。")
    positive_upload_limits = {
        "STUDYHUB_UPLOAD_AUTHORIZATION_TTL_SECONDS": settings.upload_authorization_ttl_seconds,
        "STUDYHUB_UPLOAD_DAILY_SUBMISSION_LIMIT": settings.upload_daily_submission_limit,
        "STUDYHUB_UPLOAD_DAILY_BYTES_LIMIT": settings.upload_daily_bytes_limit,
        "STUDYHUB_UPLOAD_MAX_CONCURRENT_AUTHORIZATIONS": settings.upload_max_concurrent_authorizations,
        "STUDYHUB_UPLOAD_MAX_FILE_COUNT": settings.upload_max_file_count,
        "STUDYHUB_CAPTCHA_LOCAL_MAX_ENTRIES": settings.captcha_local_max_entries,
    }
    for variable, value in positive_upload_limits.items():
        if int(value) <= 0:
            raise RuntimeError(f"{variable} 必须大于 0。")
    if not settings.resolved_upload_allowed_material_extensions:
        raise RuntimeError("STUDYHUB_UPLOAD_ALLOWED_MATERIAL_EXTENSIONS 不能为空。")


def _validate_storage(settings: Any) -> None:
    if settings.storage_provider != "oss" and settings.agentic_artifact_storage_provider != "oss":
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


def _validate_mcp(settings: Any) -> None:
    mode = settings.resolved_mcp_auth_mode
    if mode not in {"static", "oauth", "hybrid"}:
        raise RuntimeError("STUDYHUB_MCP_AUTH_MODE 只允许为 static、oauth 或 hybrid。")
    if not (settings.is_preview or settings.is_production):
        return
    if not settings.resolved_mcp_enabled:
        return
    if not settings.resolved_mcp_require_auth:
        raise RuntimeError("preview/production 开启 MCP 时必须启用 STUDYHUB_MCP_REQUIRE_AUTH。")
    if mode in {"static", "hybrid"} and not (settings.mcp_access_token or settings.mcp_access_tokens):
        raise RuntimeError("MCP static/hybrid 鉴权必须配置 STUDYHUB_MCP_ACCESS_TOKENS 或 STUDYHUB_MCP_ACCESS_TOKEN。")
    if mode in {"oauth", "hybrid"}:
        missing = []
        if not settings.resolved_mcp_oauth_authorization_servers:
            missing.append("STUDYHUB_MCP_OAUTH_AUTHORIZATION_SERVERS")
        if not settings.mcp_oauth_issuer:
            missing.append("STUDYHUB_MCP_OAUTH_ISSUER")
        if not settings.mcp_oauth_jwks_uri:
            missing.append("STUDYHUB_MCP_OAUTH_JWKS_URI")
        if not settings.resolved_mcp_oauth_audience:
            missing.append("STUDYHUB_MCP_OAUTH_AUDIENCE")
        if missing:
            raise RuntimeError(f"MCP OAuth 缺少必要配置：{', '.join(missing)}")
        authorization_servers = settings.resolved_mcp_oauth_authorization_servers
        if settings.mcp_oauth_issuer not in authorization_servers:
            raise RuntimeError("STUDYHUB_MCP_OAUTH_ISSUER 必须出现在 MCP OAuth authorization_servers 中。")
        oauth_urls = [
            *authorization_servers,
            settings.mcp_oauth_issuer,
            settings.mcp_oauth_jwks_uri,
            settings.resolved_mcp_oauth_audience,
        ]
        if any(not str(value or "").startswith("https://") for value in oauth_urls):
            raise RuntimeError("preview/production 的 MCP OAuth issuer、JWKS、audience 和授权服务器必须使用 HTTPS。")


def _validate_agentic_platform(settings: Any) -> None:
    if not settings.agentic_admin_only:
        raise RuntimeError("Agentic Platform 必须保持 STUDYHUB_AGENTIC_ADMIN_ONLY=true。")
    if settings.agentic_runtime not in {"legacy", "langgraph"}:
        raise RuntimeError("STUDYHUB_AGENTIC_RUNTIME 只允许为 legacy 或 langgraph。")
    if settings.agentic_checkpointer not in {"memory", "sqlite", "redis"}:
        raise RuntimeError("STUDYHUB_AGENTIC_CHECKPOINTER 只允许为 memory、sqlite 或 redis。")
    positive_limits = {
        "STUDYHUB_AGENTIC_MAX_TURNS": settings.agentic_max_turns,
        "STUDYHUB_AGENTIC_MAX_SKILL_CALLS": settings.agentic_max_skill_calls,
        "STUDYHUB_DEEP_RESEARCH_MAX_SEARCH_TURNS": settings.deep_research_max_search_turns,
        "STUDYHUB_DEEP_RESEARCH_MAX_PAGE_READS": settings.deep_research_max_page_reads,
        "STUDYHUB_AGENTIC_MAX_CONTEXT_TOKENS": settings.agentic_max_context_tokens,
    }
    for variable, value in positive_limits.items():
        if int(value) <= 0:
            raise RuntimeError(f"{variable} 必须大于 0。")
    if settings.agentic_proactive_enabled:
        if not settings.agentic_platform_enabled:
            raise RuntimeError("STUDYHUB_AGENTIC_PROACTIVE_ENABLED 需要先启用 STUDYHUB_AGENTIC_PLATFORM_ENABLED。")
        if settings.agentic_shadow_admin_actor_id is None or int(settings.agentic_shadow_admin_actor_id) <= 0:
            raise RuntimeError("STUDYHUB_AGENTIC_SHADOW_ADMIN_ACTOR_ID 必须是正数管理员 ID。")
    if settings.agentic_execution_enabled and not settings.agentic_platform_enabled:
        raise RuntimeError("STUDYHUB_AGENTIC_EXECUTION_ENABLED 需要先启用 STUDYHUB_AGENTIC_PLATFORM_ENABLED。")
    if settings.agentic_artifact_storage_provider not in {"local_fs", "oss"}:
        raise RuntimeError("STUDYHUB_AGENTIC_ARTIFACT_STORAGE_PROVIDER 只允许为 local_fs 或 oss。")
    if settings.agentic_model_provider not in {"disabled", "openai_compatible"}:
        raise RuntimeError("STUDYHUB_AGENTIC_MODEL_PROVIDER 只允许为 disabled 或 openai_compatible。")
    if settings.agentic_model_token_trace_source not in {"local", "teacher_api", "unavailable"}:
        raise RuntimeError("STUDYHUB_AGENTIC_MODEL_TOKEN_TRACE_SOURCE 配置非法。")
    if settings.agentic_model_timeout_seconds <= 0:
        raise RuntimeError("STUDYHUB_AGENTIC_MODEL_TIMEOUT_SECONDS 必须大于 0。")
    if int(settings.agentic_model_max_retries) < 0:
        raise RuntimeError("STUDYHUB_AGENTIC_MODEL_MAX_RETRIES 不能小于 0。")
    if settings.agentic_execution_enabled:
        required_model_settings = {
            "STUDYHUB_AGENTIC_MODEL_BASE_URL": settings.agentic_model_base_url,
            "STUDYHUB_AGENTIC_MODEL_API_KEY": settings.agentic_model_api_key,
            "STUDYHUB_AGENTIC_MODEL_ID": settings.agentic_model_id,
        }
        if settings.agentic_model_provider != "openai_compatible" or any(
            not isinstance(value, str) or not value.strip() for value in required_model_settings.values()
        ):
            raise RuntimeError("启用 Agent Execution 前必须完整配置 OpenAI-compatible Agentic Model Provider。")
        if not isinstance(settings.agentic_retriever_version, str) or not settings.agentic_retriever_version.strip():
            raise RuntimeError("启用 Agent Execution 前必须配置 STUDYHUB_AGENTIC_RETRIEVER_VERSION。")
        if settings.agentic_runtime != "langgraph":
            raise RuntimeError("启用 Agent Execution 时必须使用 STUDYHUB_AGENTIC_RUNTIME=langgraph。")
        if settings.agentic_checkpointer != "sqlite":
            raise RuntimeError("启用 Agent Execution 时必须使用可恢复的 STUDYHUB_AGENTIC_CHECKPOINTER=sqlite。")
        if not settings.agentic_durable_storage_enabled:
            raise RuntimeError("启用 Agent Execution 前必须设置 STUDYHUB_AGENTIC_DURABLE_STORAGE_ENABLED=true。")
        if settings.is_production and settings.agentic_artifact_storage_provider != "oss":
            raise RuntimeError("production Agent Execution 必须使用 STUDYHUB_AGENTIC_ARTIFACT_STORAGE_PROVIDER=oss。")
    positive_worker_limits = {
        "STUDYHUB_AGENTIC_WORKER_LOCK_TIMEOUT_SECONDS": settings.agentic_worker_lock_timeout_seconds,
        "STUDYHUB_AGENTIC_WORKER_BATCH_SIZE": settings.agentic_worker_batch_size,
        "STUDYHUB_AGENTIC_WORKER_CLAIM_TTL_SECONDS": settings.agentic_worker_claim_ttl_seconds,
        "STUDYHUB_AGENTIC_WORKER_MAX_ATTEMPTS": settings.agentic_worker_max_attempts,
    }
    for variable, value in positive_worker_limits.items():
        if int(value) <= 0:
            raise RuntimeError(f"{variable} 必须大于 0。")
    if int(settings.agentic_worker_retry_delay_seconds) < 0:
        raise RuntimeError("STUDYHUB_AGENTIC_WORKER_RETRY_DELAY_SECONDS 不能小于 0。")
    positive_execution_limits = {
        "STUDYHUB_AGENTIC_EXECUTION_BATCH_SIZE": settings.agentic_execution_batch_size,
        "STUDYHUB_AGENTIC_EXECUTION_CLAIM_TTL_SECONDS": settings.agentic_execution_claim_ttl_seconds,
        "STUDYHUB_AGENTIC_EXECUTION_MAX_ATTEMPTS": settings.agentic_execution_max_attempts,
    }
    for variable, value in positive_execution_limits.items():
        if int(value) <= 0:
            raise RuntimeError(f"{variable} 必须大于 0。")


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
    if not settings.resolved_trusted_hosts:
        raise RuntimeError("production 模式必须配置 STUDYHUB_TRUSTED_HOSTS。")
