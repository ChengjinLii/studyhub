from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.agentic_platform.application import AdminAgentRunService
from app.agentic_platform.application.runtime_events import RuntimeEventStore
from app.agentic_platform.execution import (
    AgentExecutionWorker,
    AgentRuntimeFactory,
    DurableRuntimeDependencies,
    build_durable_agent_runtime_factory,
)
from app.agentic_platform.proactive.dispatcher import ProactiveDispatcher
from app.agentic_platform.proactive.jobs import ProactiveAgentWorker
from app.agentic_platform.proactive.outbox import AgentOutboxRepository
from app.agentic_platform.proactive.triggers import ProactiveTriggerService
from app.agentic_platform.skills.registry import SkillRegistry, build_default_skill_registry
from app.core.config import get_settings
from app.core.db import get_db_session, get_session_factory
from app.core.public_read_cache import PublicReadCache
from app.core.security import AuthContext, JwtTokenCodec, resolve_token_from_request
from app.integrations.material_asset_store import MaterialAssetStore
from app.integrations.market_asset_store import MarketAssetStore
from app.integrations.payout_qr_store import PayoutQrStore
from app.providers.kyc import AliyunCloudAuthKycProvider, KycProvider, LocalMockKycProvider
from app.providers.lock import DbRowLockProvider, LockProvider, RedisLockProvider
from app.providers.mail import LocalOutboxMailProvider, MailProvider, SmtpMailProvider
from app.providers.payment import AlipayPagePaymentProvider, LocalAlipayPaymentProvider, PaymentGatewayProvider
from app.providers.storage import AliyunOssStorageProvider, LocalFileStorageProvider, StorageProvider
from app.providers.transfer import AlipayTransferProvider, LocalTransferProvider, PayoutTransferProvider
from app.repos.auth_repo import AuthRepository
from app.repos.agentic_artifact_repo import AgentArtifactRepository
from app.repos.agentic_run_repo import AgentRunRepository
from app.repos.admin_repo import AdminRepository
from app.repos.comment_repo import CommentRepository
from app.repos.community_repo import CommunityRepository
from app.repos.finance_repo import FinanceRepository
from app.repos.material_catalog_repo import MaterialCatalogRepository
from app.repos.material_repo import MaterialRepository
from app.repos.market_repo import MarketRepository
from app.repos.read_api_repo import ReadApiRepository
from app.repos.request_repo import RequestRepository
from app.repos.system_repo import SystemRepository
from app.repos.user_follow_repo import UserFollowRepository
from app.services.account_service import AccountService
from app.services.admin_user_service import AdminUserService
from app.services.agent_course_memory_service import AgentCourseMemoryService
from app.services.agent_conversation_memory_service import AgentConversationMemoryService
from app.services.agent_feedback_service import AgentFeedbackService
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_query_planner_service import AgentQueryPlannerService
from app.services.ai_service import AiService
from app.services.auth_cookie_service import AuthCookieService
from app.services.auth_service import AuthService
from app.services.captcha_service import CaptchaService
from app.services.comments_service import CommentsService
from app.services.community_service import CommunityService
from app.services.health_service import HealthService
from app.services.leaderboard_read_service import LeaderboardReadService
from app.services.materials_service import MaterialsService
from app.services.materials_column_service import MaterialsColumnService
from app.services.material_pdf_evidence_service import MaterialPdfEvidenceService
from app.services.market_service import MarketService
from app.services.payment_service import PaymentService
from app.services.notification_service import NotificationService
from app.services.payout_service import PayoutService
from app.services.requests_service import RequestsService
from app.services.report_service import ReportService
from app.services.kyc_crypto_service import KycCryptoService
from app.services.read_support import ROLE_ADMIN, ROLE_DEVELOPER, has_role
from app.services.session_service import SessionService
from app.services.user_follow_service import UserFollowService
from app.services.user_read_service import UserReadService
from app.services.worker_service import WorkerService


@lru_cache(maxsize=1)
def get_material_catalog_repo() -> MaterialCatalogRepository:
    settings = get_settings()
    return MaterialCatalogRepository(settings.resolved_material_column_seed_path)


@lru_cache(maxsize=1)
def get_read_api_repo() -> ReadApiRepository:
    settings = get_settings()
    return ReadApiRepository(settings.resolved_read_api_seed_path)


@lru_cache(maxsize=1)
def get_public_read_cache() -> PublicReadCache:
    return PublicReadCache(get_settings())


@lru_cache(maxsize=1)
def get_system_repo() -> SystemRepository:
    return SystemRepository()


@lru_cache(maxsize=1)
def get_auth_repo() -> AuthRepository:
    return AuthRepository()


@lru_cache(maxsize=1)
def get_admin_repo() -> AdminRepository:
    return AdminRepository()


@lru_cache(maxsize=1)
def get_material_repo() -> MaterialRepository:
    return MaterialRepository()


@lru_cache(maxsize=1)
def get_agentic_skill_registry() -> SkillRegistry:
    """Build the dormant registry without enabling or exposing the platform."""

    return build_default_skill_registry()


@lru_cache(maxsize=1)
def get_admin_agent_run_service() -> AdminAgentRunService:
    """The admin control plane is inert until the feature flags allow its routes."""

    return AdminAgentRunService(get_settings())


@lru_cache(maxsize=1)
def get_proactive_trigger_service() -> ProactiveTriggerService:
    return ProactiveTriggerService(get_settings())


@lru_cache(maxsize=1)
def get_proactive_agent_worker() -> ProactiveAgentWorker:
    settings = get_settings()
    outbox = AgentOutboxRepository()
    runs = AgentRunRepository()
    artifacts = AgentArtifactRepository()
    events = RuntimeEventStore(artifacts)
    triggers = ProactiveTriggerService(settings, outbox_repository=outbox)
    dispatcher = ProactiveDispatcher(
        settings,
        run_repository=runs,
        outbox_repository=outbox,
        events=events,
    )
    return ProactiveAgentWorker(
        settings,
        triggers=triggers,
        dispatcher=dispatcher,
        outbox_repository=outbox,
        run_repository=runs,
        artifact_repository=artifacts,
        material_repository=get_material_repo(),
        pdf_evidence_service=MaterialPdfEvidenceService(settings, get_material_asset_store()),
        events=events,
    )


@lru_cache(maxsize=1)
def get_agent_runtime_factory() -> AgentRuntimeFactory:
    """Bind the real model/runtime only after its independent opt-in is on."""

    settings = get_settings()
    if not settings.agentic_execution_enabled:
        return AgentRuntimeFactory()
    return build_durable_agent_runtime_factory(
        settings,
        dependencies=DurableRuntimeDependencies(
            session_factory=get_session_factory(),
            skill_registry=get_agentic_skill_registry(),
            material_repository=get_material_repo(),
            materials_service=get_materials_service(),
            pdf_evidence_service=MaterialPdfEvidenceService(settings, get_material_asset_store()),
            storage_provider=(
                AliyunOssStorageProvider(settings)
                if settings.agentic_artifact_storage_provider == "oss"
                else get_storage_provider()
            ),
        ),
    )


@lru_cache(maxsize=1)
def get_agent_execution_worker() -> AgentExecutionWorker:
    settings = get_settings()
    artifacts = AgentArtifactRepository()
    return AgentExecutionWorker(
        settings,
        runtime_factory=get_agent_runtime_factory(),
        lock_provider=get_lock_provider(),
        run_repository=AgentRunRepository(),
        artifact_repository=artifacts,
        events=RuntimeEventStore(artifacts),
    )


@lru_cache(maxsize=1)
def get_comment_repo() -> CommentRepository:
    return CommentRepository()


@lru_cache(maxsize=1)
def get_market_repo() -> MarketRepository:
    return MarketRepository()


@lru_cache(maxsize=1)
def get_community_repo() -> CommunityRepository:
    return CommunityRepository()


@lru_cache(maxsize=1)
def get_user_follow_repo() -> UserFollowRepository:
    return UserFollowRepository()


@lru_cache(maxsize=1)
def get_request_repo() -> RequestRepository:
    return RequestRepository()


@lru_cache(maxsize=1)
def get_finance_repo() -> FinanceRepository:
    return FinanceRepository()


@lru_cache(maxsize=1)
def get_token_codec() -> JwtTokenCodec:
    settings = get_settings()
    return JwtTokenCodec(settings.jwt_secret, settings.jwt_algorithm)


@lru_cache(maxsize=1)
def get_captcha_service() -> CaptchaService:
    return CaptchaService(get_settings())


@lru_cache(maxsize=1)
def get_auth_cookie_service() -> AuthCookieService:
    return AuthCookieService(get_settings(), get_token_codec())


@lru_cache(maxsize=1)
def get_mail_provider() -> MailProvider:
    settings = get_settings()
    if settings.mail_provider == "local_outbox":
        return LocalOutboxMailProvider(settings)
    if settings.mail_provider == "smtp":
        return SmtpMailProvider(settings)
    raise ValueError(f"Unsupported mail provider: {settings.mail_provider}")


@lru_cache(maxsize=1)
def get_storage_provider() -> StorageProvider:
    settings = get_settings()
    if settings.storage_provider == "local_fs":
        return LocalFileStorageProvider()
    if settings.storage_provider == "oss":
        return AliyunOssStorageProvider(settings)
    raise ValueError(f"Unsupported storage provider: {settings.storage_provider}")


@lru_cache(maxsize=1)
def get_payment_provider() -> PaymentGatewayProvider:
    settings = get_settings()
    if settings.payment_provider == "local_alipay":
        return LocalAlipayPaymentProvider()
    if settings.payment_provider == "alipay_page":
        return AlipayPagePaymentProvider(settings)
    raise ValueError(f"Unsupported payment provider: {settings.payment_provider}")


@lru_cache(maxsize=1)
def get_transfer_provider() -> PayoutTransferProvider:
    settings = get_settings()
    if settings.payout_transfer_provider == "local_transfer":
        return LocalTransferProvider()
    if settings.payout_transfer_provider == "alipay_transfer":
        return AlipayTransferProvider(settings)
    raise ValueError(f"Unsupported payout transfer provider: {settings.payout_transfer_provider}")


@lru_cache(maxsize=1)
def get_kyc_provider() -> KycProvider:
    settings = get_settings()
    if settings.kyc_provider == "mock_local":
        return LocalMockKycProvider()
    if settings.kyc_provider == "aliyun_cloud_auth":
        return AliyunCloudAuthKycProvider(settings)
    raise ValueError(f"Unsupported KYC provider: {settings.kyc_provider}")


@lru_cache(maxsize=1)
def get_lock_provider() -> LockProvider:
    settings = get_settings()
    if settings.lock_provider == "db_row":
        return DbRowLockProvider(get_finance_repo())
    if settings.lock_provider == "redis":
        return RedisLockProvider(settings)
    raise ValueError(f"Unsupported lock provider: {settings.lock_provider}")


@lru_cache(maxsize=1)
def get_kyc_crypto_service() -> KycCryptoService:
    return KycCryptoService(get_settings())


@lru_cache(maxsize=1)
def get_material_asset_store() -> MaterialAssetStore:
    return MaterialAssetStore(get_settings(), get_token_codec(), get_storage_provider())


@lru_cache(maxsize=1)
def get_market_asset_store() -> MarketAssetStore:
    return MarketAssetStore(get_settings(), get_storage_provider())


@lru_cache(maxsize=1)
def get_payout_qr_store() -> PayoutQrStore:
    return PayoutQrStore(get_settings(), get_storage_provider())


@lru_cache(maxsize=1)
def get_health_service() -> HealthService:
    return HealthService(
        get_settings(),
        get_system_repo(),
        get_mail_provider(),
        get_storage_provider(),
        get_payment_provider(),
        get_transfer_provider(),
        get_kyc_provider(),
        get_lock_provider(),
    )


@lru_cache(maxsize=1)
def get_session_service() -> SessionService:
    return SessionService(get_settings(), get_auth_cookie_service())


@lru_cache(maxsize=1)
def get_materials_column_service() -> MaterialsColumnService:
    return MaterialsColumnService(get_settings(), get_material_catalog_repo())


@lru_cache(maxsize=1)
def get_user_read_service() -> UserReadService:
    return UserReadService(
        get_read_api_repo(),
        get_auth_repo(),
        get_user_follow_service(),
        get_material_repo(),
        get_market_repo(),
        get_finance_repo(),
    )


@lru_cache(maxsize=1)
def get_materials_service() -> MaterialsService:
    return MaterialsService(
        get_settings(),
        get_read_api_repo(),
        get_auth_repo(),
        get_material_repo(),
        get_material_asset_store(),
        get_proactive_trigger_service(),
    )


@lru_cache(maxsize=1)
def get_leaderboard_read_service() -> LeaderboardReadService:
    return LeaderboardReadService(get_settings(), get_read_api_repo())


@lru_cache(maxsize=1)
def get_market_service() -> MarketService:
    return MarketService(get_settings(), get_read_api_repo(), get_auth_repo(), get_market_repo(), get_market_asset_store())


@lru_cache(maxsize=1)
def get_report_service() -> ReportService:
    return ReportService(
        get_read_api_repo(),
        get_auth_repo(),
        get_material_repo(),
        get_comment_repo(),
        get_market_repo(),
        get_community_repo(),
    )


@lru_cache(maxsize=1)
def get_comments_service() -> CommentsService:
    return CommentsService(
        get_settings(),
        get_read_api_repo(),
        get_auth_repo(),
        get_material_repo(),
        get_comment_repo(),
        get_report_service(),
    )


@lru_cache(maxsize=1)
def get_community_service() -> CommunityService:
    return CommunityService(get_community_repo())


@lru_cache(maxsize=1)
def get_notification_service() -> NotificationService:
    return NotificationService(get_auth_repo(), get_community_repo(), get_market_repo())


@lru_cache(maxsize=1)
def get_requests_service() -> RequestsService:
    return RequestsService(
        get_settings(),
        get_read_api_repo(),
        get_auth_repo(),
        get_material_repo(),
        get_request_repo(),
        get_finance_repo(),
        get_payment_provider(),
    )


@lru_cache(maxsize=1)
def get_payment_service() -> PaymentService:
    return PaymentService(
        get_settings(),
        get_read_api_repo(),
        get_auth_repo(),
        get_material_repo(),
        get_finance_repo(),
        get_requests_service(),
        get_payment_provider(),
    )


@lru_cache(maxsize=1)
def get_payout_service() -> PayoutService:
    return PayoutService(
        get_settings(),
        get_auth_repo(),
        get_finance_repo(),
        get_payout_qr_store(),
        get_kyc_provider(),
        get_kyc_crypto_service(),
        get_transfer_provider(),
    )


@lru_cache(maxsize=1)
def get_worker_service() -> WorkerService:
    return WorkerService(
        get_settings(),
        get_payout_service(),
        get_requests_service(),
        get_lock_provider(),
        agentic_worker=get_proactive_agent_worker(),
        agentic_execution_worker=get_agent_execution_worker(),
    )


@lru_cache(maxsize=1)
def get_admin_user_service() -> AdminUserService:
    return AdminUserService(get_read_api_repo(), get_admin_repo(), get_auth_repo(), get_auth_service())


@lru_cache(maxsize=1)
def get_ai_service() -> AiService:
    return AiService(
        get_read_api_repo(),
        get_material_repo(),
        MaterialPdfEvidenceService(get_settings(), get_material_asset_store()),
        AgentMemoryService(get_settings(), get_auth_repo(), get_material_repo()),
        AgentQueryPlannerService(),
        AgentCourseMemoryService(),
        conversation_memory_service=AgentConversationMemoryService(get_settings()),
    )


@lru_cache(maxsize=1)
def get_agent_feedback_service() -> AgentFeedbackService:
    return AgentFeedbackService(get_material_repo())


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    return AuthService(
        get_settings(),
        get_auth_repo(),
        get_captcha_service(),
        get_auth_cookie_service(),
        get_mail_provider(),
    )


@lru_cache(maxsize=1)
def get_user_follow_service() -> UserFollowService:
    return UserFollowService(get_user_follow_repo(), get_auth_repo())


@lru_cache(maxsize=1)
def get_account_service() -> AccountService:
    return AccountService(get_auth_repo(), get_read_api_repo())


def get_optional_auth_context(
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthContext | None:
    settings = get_settings()
    token, source = resolve_token_from_request(request, settings.cookie_token_name)
    if not token:
        return None
    try:
        claims = dict(get_token_codec().decode(token))
        user_id = int(claims["sub"])
    except Exception:  # noqa: BLE001
        return None

    user = get_auth_repo().find_user_by_id(session, user_id)
    if user is None:
        return None
    role_mask = user.role_mask

    return AuthContext(
        user_id=user_id,
        role_mask=role_mask,
        source=source,
        token=token,
        claims=claims,
    )


def require_auth_context(auth: AuthContext | None = Depends(get_optional_auth_context)) -> AuthContext:
    if auth is None or auth.user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return auth


def require_privileged_auth_context(auth: AuthContext = Depends(require_auth_context)) -> AuthContext:
    if not has_role(auth.role_mask, ROLE_ADMIN) and not has_role(auth.role_mask, ROLE_DEVELOPER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问管理接口")
    return auth


def require_admin_agent_context(auth: AuthContext = Depends(require_auth_context)) -> AuthContext:
    """Strict boundary for the new agentic platform; developers are not administrators here."""

    if not has_role(auth.role_mask, ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agentic research platform is admin-only",
        )
    return auth


def require_enabled_admin_agent_context(
    auth: AuthContext = Depends(require_admin_agent_context),
) -> AuthContext:
    if not get_settings().agentic_platform_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agentic research platform is disabled",
        )
    return auth


def require_enabled_deep_research_admin_context(
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
) -> AuthContext:
    if not get_settings().deep_research_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deep research is disabled",
        )
    return auth


def clear_dependency_caches() -> None:
    get_public_read_cache.cache_clear()
    get_material_catalog_repo.cache_clear()
    get_read_api_repo.cache_clear()
    get_system_repo.cache_clear()
    get_auth_repo.cache_clear()
    get_admin_repo.cache_clear()
    get_material_repo.cache_clear()
    get_agentic_skill_registry.cache_clear()
    get_admin_agent_run_service.cache_clear()
    get_proactive_trigger_service.cache_clear()
    get_proactive_agent_worker.cache_clear()
    get_agent_runtime_factory.cache_clear()
    get_agent_execution_worker.cache_clear()
    get_comment_repo.cache_clear()
    get_market_repo.cache_clear()
    get_community_repo.cache_clear()
    get_user_follow_repo.cache_clear()
    get_request_repo.cache_clear()
    get_finance_repo.cache_clear()
    get_token_codec.cache_clear()
    get_captcha_service.cache_clear()
    get_auth_cookie_service.cache_clear()
    get_mail_provider.cache_clear()
    get_storage_provider.cache_clear()
    get_payment_provider.cache_clear()
    get_transfer_provider.cache_clear()
    get_kyc_provider.cache_clear()
    get_kyc_crypto_service.cache_clear()
    get_lock_provider.cache_clear()
    get_material_asset_store.cache_clear()
    get_market_asset_store.cache_clear()
    get_payout_qr_store.cache_clear()
    get_health_service.cache_clear()
    get_session_service.cache_clear()
    get_materials_column_service.cache_clear()
    get_user_read_service.cache_clear()
    get_materials_service.cache_clear()
    get_leaderboard_read_service.cache_clear()
    get_market_service.cache_clear()
    get_report_service.cache_clear()
    get_comments_service.cache_clear()
    get_community_service.cache_clear()
    get_notification_service.cache_clear()
    get_requests_service.cache_clear()
    get_payment_service.cache_clear()
    get_payout_service.cache_clear()
    get_worker_service.cache_clear()
    get_admin_user_service.cache_clear()
    get_ai_service.cache_clear()
    get_agent_feedback_service.cache_clear()
    get_auth_service.cache_clear()
    get_user_follow_service.cache_clear()
    get_account_service.cache_clear()
