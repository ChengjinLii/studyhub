"""SQLAlchemy models live here as the migration proceeds."""

from app.models.admin import UserNoteRecord
from app.models.auth import AuthSessionStateRecord, AuthUser, EmailVerification
from app.models.base import Base
from app.models.comments import CommentLikeRecord, CommentRecord
from app.models.community import FeedbackRecord, NotificationRecord, ReportRecord, VolunteerApplicationRecord
from app.models.finance import (
    AdminMonthlyPayoutMarkRecord,
    AlipayGatewayNotificationRecord,
    CreatorPayoutApplicationRecord,
    FinanceInstructionRecord,
    OrderRecord,
    PaymentNotificationRecord,
    PaymentRecord,
    PayoutScheduleRecord,
    PayoutTransferRecord,
    SettlementRecord,
    WorkerLockRecord,
)
from app.models.materials import (
    MaterialDownloadRecord,
    MaterialFavoriteRecord,
    MaterialLikeRecord,
    MaterialPurchaseRecord,
    MaterialRatingRecord,
    MaterialRecord,
    MaterialReviewRecord,
    MaterialSecurityScanRecord,
    MaterialVersionRecord,
    MaterialViewRecord,
)
from app.models.market import MarketItemRecord, MarketWantRecord
from app.models.requests import (
    RequestArbitrationRecord,
    RequestContributionRecord,
    RequestPreviewViewRecord,
    RequestRecord,
    RequestResponseRecord,
)
from app.models.social import UserFollow

__all__ = [
    "AuthUser",
    "AuthSessionStateRecord",
    "AdminMonthlyPayoutMarkRecord",
    "AlipayGatewayNotificationRecord",
    "FinanceInstructionRecord",
    "Base",
    "CommentLikeRecord",
    "CommentRecord",
    "CreatorPayoutApplicationRecord",
    "EmailVerification",
    "FeedbackRecord",
    "MaterialDownloadRecord",
    "MaterialFavoriteRecord",
    "MaterialLikeRecord",
    "MaterialPurchaseRecord",
    "MaterialRatingRecord",
    "MaterialRecord",
    "MaterialReviewRecord",
    "MaterialSecurityScanRecord",
    "MaterialVersionRecord",
    "MaterialViewRecord",
    "MarketItemRecord",
    "MarketWantRecord",
    "NotificationRecord",
    "OrderRecord",
    "PaymentNotificationRecord",
    "PaymentRecord",
    "PayoutScheduleRecord",
    "PayoutTransferRecord",
    "ReportRecord",
    "RequestArbitrationRecord",
    "RequestContributionRecord",
    "RequestPreviewViewRecord",
    "RequestRecord",
    "RequestResponseRecord",
    "SettlementRecord",
    "UserNoteRecord",
    "UserFollow",
    "VolunteerApplicationRecord",
    "WorkerLockRecord",
]
