from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.upload_validation import validate_image_upload
from app.models.auth import AuthUser
from app.models.finance import (
    AdminMonthlyPayoutMarkRecord,
    AlipayGatewayNotificationRecord,
    CreatorPayoutApplicationRecord,
    OrderRecord,
    PayoutScheduleRecord,
    PayoutTransferRecord,
    SettlementRecord,
)
from app.providers.kyc import KycProvider
from app.providers.transfer import PayoutTransferProvider, TransferResult
from app.repos.auth_repo import AuthRepository
from app.repos.finance_repo import FinanceRepository
from app.services.kyc_crypto_service import KycCryptoService
from app.services.read_support import build_payout_qr_url
from app.integrations.payout_qr_store import PayoutQrStore


SH_TZ = ZoneInfo("Asia/Shanghai")
PAYOUT_STATUS_PENDING = "PENDING"
PAYOUT_STATUS_APPROVED = "APPROVED"
PAYOUT_STATUS_REJECTED = "REJECTED"
PAYOUT_STATUS_SETTLED = "SETTLED"
PAYOUT_STATUS_KYC_FAILED = "KYC_FAILED"
PAYOUT_STATUS_KYC_PENDING = "KYC_PENDING"
KYC_STATUS_VERIFIED = "VERIFIED"
KYC_STATUS_FAILED = "FAILED"
KYC_STATUS_PENDING = "PENDING"
TRANSFER_STATUS_SUBMITTED = "SUBMITTED"
TRANSFER_STATUS_PENDING = "PENDING"
TRANSFER_STATUS_SUCCESS = "SUCCESS"
TRANSFER_STATUS_FAILED = "FAILED"


class PayoutService:
    """
    提现、结算、收款码和月度打款概览统一放在这里。
    """

    def __init__(
        self,
        settings: Settings,
        auth_repo: AuthRepository,
        finance_repo: FinanceRepository,
        payout_qr_store: PayoutQrStore,
        kyc_provider: KycProvider,
        kyc_crypto_service: KycCryptoService,
        transfer_provider: PayoutTransferProvider,
    ) -> None:
        self.settings = settings
        self.auth_repo = auth_repo
        self.finance_repo = finance_repo
        self.payout_qr_store = payout_qr_store
        self.kyc_provider = kyc_provider
        self.kyc_crypto_service = kyc_crypto_service
        self.transfer_provider = transfer_provider

    def upload_payout_qr(self, session: Session, *, user_id: int, upload: UploadFile) -> dict[str, Any]:
        validate_image_upload(
            upload,
            settings=self.settings,
            max_size_bytes=self.settings.payout_qr_max_size_bytes,
            missing_detail="请先选择收款码图片",
            invalid_type_detail="收款码仅支持 PNG、JPG、WEBP、GIF、BMP、AVIF、HEIC、HEIF 格式",
            too_large_detail="收款码图片不能超过 5MB",
        )

        user = self._require_user(session, user_id)
        previous_key = user.payout_qr_key
        key = self.payout_qr_store.save_upload(user_id=user_id, upload=upload)
        user.payout_qr_key = key
        self.auth_repo.save_user(session, user)
        session.commit()
        if previous_key and previous_key != key:
            self.payout_qr_store.delete_key(previous_key)
        return self._account_payload(user)

    def clear_payout_qr(self, session: Session, *, user_id: int) -> dict[str, Any]:
        user = self._require_user(session, user_id)
        previous_key = user.payout_qr_key
        user.payout_qr_key = None
        self.auth_repo.save_user(session, user)
        session.commit()
        if previous_key:
            self.payout_qr_store.delete_key(previous_key)
        return self._account_payload(user)

    def resolve_payout_qr_asset(
        self,
        session: Session,
        *,
        target_user_id: int,
        viewer_user_id: int,
        viewer_role_mask: int | None,
    ) -> tuple[Path | None, str, str | None]:
        user = self._require_user(session, target_user_id)
        if not user.payout_qr_key:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="收款码不存在")
        is_owner = target_user_id == viewer_user_id
        is_admin = viewer_role_mask is not None and (viewer_role_mask & 8) == 8
        if not is_owner and not is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该收款码")
        media_type = self.payout_qr_store.guess_media_type(user.payout_qr_key, default="image/png")
        direct_url = self.payout_qr_store.build_private_access_url(key=user.payout_qr_key)
        if direct_url is not None:
            return None, media_type, direct_url
        path = self.payout_qr_store.resolve_path(user.payout_qr_key)
        return path, media_type, None

    def get_latest_for_user(self, session: Session, *, user_id: int) -> dict[str, Any]:
        self._require_user(session, user_id)
        cycle = self._resolve_current_cycle(session, allow_default=True)
        earnings = self._build_earnings(session, user_id)
        entity = self.finance_repo.find_latest_payout_application_for_user(session, user_id)
        if entity is None:
            return {
                "cycleKey": cycle["cycleKey"],
                "cycleStartDate": cycle["cycleStartDate"],
                "cycleEndDate": cycle["cycleEndDate"],
                "earnings": earnings,
            }
        return self._to_application_payload(session, entity, earnings=earnings)

    def create_application(self, session: Session, *, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        user = self._require_user(session, user_id)
        cycle = self._resolve_current_cycle(session, allow_default=True)
        earnings = self._build_earnings(session, user_id)
        if int(earnings["payoutAmount"]) < self.settings.payout_min_amount_cents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="最低提现金额为 10 元")

        entity = self.finance_repo.find_payout_application_by_user_cycle(session, user_id, cycle["cycleKey"])
        if entity is not None and entity.status not in {PAYOUT_STATUS_REJECTED, PAYOUT_STATUS_KYC_FAILED, PAYOUT_STATUS_KYC_PENDING}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="本结算周期已提交，请下个周期再申请")
        if entity is None:
            entity = CreatorPayoutApplicationRecord(
                user_id=user_id,
                cycle_key=cycle["cycleKey"],
                cycle_start_date=cycle["cycleStartDate"],
                cycle_end_date=cycle["cycleEndDate"],
            )

        real_name = str(payload.get("realName") or payload.get("alipayName") or "").strip()
        id_card = str(payload.get("idCardNo") or "").strip().upper()
        if not real_name or not id_card:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请填写实名姓名与身份证号")

        alipay_account = str(payload.get("alipayAccount") or "").strip()
        kyc_decision = self._verify_kyc(session, user_id=user_id, entity=entity, real_name=real_name, id_card=id_card)
        try:
            entity.real_name_encrypted = self.kyc_crypto_service.encrypt(real_name)
            entity.alipay_account_encrypted = self.kyc_crypto_service.encrypt(alipay_account)
            entity.alipay_name_encrypted = self.kyc_crypto_service.encrypt(real_name)
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="实名核验配置缺失") from exc
        entity.alipay_account = self.kyc_crypto_service.mask_account(alipay_account)
        entity.alipay_name = self.kyc_crypto_service.mask_name(real_name)
        entity.id_hash = kyc_decision["idHash"]
        entity.id_last4 = kyc_decision["idLast4"]
        entity.contact_type = str(payload.get("contactType") or "").strip() or None
        entity.contact_value = str(payload.get("contactValue") or "").strip() or None
        entity.notes = str(payload.get("notes") or "").strip() or None
        entity.reviewer_id = None
        entity.review_notes = None
        entity.settled_at = None
        entity.kyc_status = str(kyc_decision["kycStatus"])
        entity.kyc_verified_at = kyc_decision["verifiedAt"]
        entity.kyc_provider = str(kyc_decision["provider"])
        entity.kyc_request_id = str(kyc_decision["requestId"])
        entity.kyc_biz_code = str(kyc_decision["bizCode"])
        entity.kyc_biz_message = str(kyc_decision["bizMessage"])

        if entity.kyc_status == KYC_STATUS_VERIFIED:
            entity.status = PAYOUT_STATUS_PENDING
        elif entity.kyc_status == KYC_STATUS_PENDING:
            entity.status = PAYOUT_STATUS_KYC_PENDING
        else:
            entity.status = PAYOUT_STATUS_KYC_FAILED

        self.finance_repo.save_payout_application(session, entity)
        session.commit()
        return self._to_application_payload(session, entity, earnings=earnings)

    def list_for_admin(self, session: Session, *, page: int, size: int) -> dict[str, Any]:
        items, total = self.finance_repo.list_payout_applications(session, page=page, size=size)
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        return {
            "items": [self._to_application_payload(session, item) for item in items],
            "page": safe_page,
            "size": safe_size,
            "total": total,
        }

    def review_application(
        self,
        session: Session,
        *,
        admin_id: int,
        application_id: int,
        status_value: str,
        review_notes: str | None,
    ) -> dict[str, Any]:
        self._require_user(session, admin_id)
        entity = self.finance_repo.get_payout_application(session, application_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请不存在")

        if status_value == PAYOUT_STATUS_APPROVED and entity.kyc_status != KYC_STATUS_VERIFIED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="实名核验未通过，无法打款")

        entity.reviewer_id = admin_id
        entity.review_notes = review_notes or entity.review_notes

        if status_value == PAYOUT_STATUS_APPROVED:
            earnings = self._build_earnings(session, entity.user_id)
            if int(earnings["payoutAmount"]) < self.settings.payout_min_amount_cents:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="可提现金额不足 10 元")
            entity.status = PAYOUT_STATUS_APPROVED
            self._ensure_transfer(session, entity, amount_cents=int(earnings["payoutAmount"]))
        else:
            entity.status = PAYOUT_STATUS_REJECTED

        self.finance_repo.save_payout_application(session, entity)
        session.commit()
        return self._to_application_payload(session, entity, earnings=self._build_earnings(session, entity.user_id))

    def list_settlement_details(self, session: Session, *, application_id: int) -> list[dict[str, Any]]:
        entity = self.finance_repo.get_payout_application(session, application_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请不存在")
        now = datetime.now(UTC)
        items = self.finance_repo.list_pending_due_settlements_for_uploader(session, entity.user_id, now)
        return [self._to_settlement_detail(item) for item in items]

    def get_schedule(self, session: Session) -> dict[str, Any]:
        schedule = self.finance_repo.get_payout_schedule(session)
        if schedule is None or schedule.launch_date is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先在后台配置上线日期/结算日")
        return self._to_schedule_payload(schedule)

    def update_schedule(self, session: Session, *, launch_date: date, next_payout_date: date | None) -> dict[str, Any]:
        schedule = self.finance_repo.get_payout_schedule(session)
        if schedule is None:
            schedule = PayoutScheduleRecord()
        schedule.launch_date = launch_date
        schedule.next_payout_date = next_payout_date or (launch_date + timedelta(days=7))
        if schedule.last_payout_date is None and schedule.next_payout_date is not None and schedule.next_payout_date < launch_date:
            schedule.last_payout_date = launch_date
        self.finance_repo.save_payout_schedule(session, schedule)
        session.commit()
        return self._to_schedule_payload(schedule)

    def get_monthly_overview(self, session: Session, *, month_key_raw: str | None) -> dict[str, Any]:
        month = self._resolve_month(month_key_raw)
        month_key = month.strftime("%Y-%m")
        start_dt = datetime(month.year, month.month, 1, tzinfo=SH_TZ)
        if month.month == 12:
            end_dt = datetime(month.year + 1, 1, 1, tzinfo=SH_TZ)
        else:
            end_dt = datetime(month.year, month.month + 1, 1, tzinfo=SH_TZ)

        rows = self.finance_repo.list_paid_orders_between(session, start_dt.astimezone(UTC), end_dt.astimezone(UTC))
        grouped: dict[int, dict[str, Any]] = {}
        for order in rows:
            if order.uploader_id is None:
                continue
            item = grouped.setdefault(
                int(order.uploader_id),
                {
                    "uploaderId": int(order.uploader_id),
                    "uploaderUsername": None,
                    "uploaderNickname": None,
                    "paidDownloadCount": 0,
                    "payoutAmount": 0,
                    "hasPayoutQr": False,
                    "markedPaid": False,
                    "markedAt": None,
                    "markedById": None,
                    "markedByName": None,
                    "markedAmountSnapshot": None,
                },
            )
            item["paidDownloadCount"] += 1
            item["payoutAmount"] += int(order.creator_payable_amount or max(0, int(order.amount or 0) - int(order.platform_fee_amount or 0)))

        marks = {mark.uploader_id: mark for mark in self.finance_repo.list_monthly_payout_marks(session, month_key)}
        for uploader_id, item in grouped.items():
            self._hydrate_monthly_user_fields(session, item, uploader_id)
            self._apply_monthly_mark(session, item, marks.get(uploader_id))

        for mark in marks.values():
            if mark.uploader_id in grouped:
                continue
            item = {
                "uploaderId": int(mark.uploader_id),
                "uploaderUsername": None,
                "uploaderNickname": None,
                "paidDownloadCount": 0,
                "payoutAmount": int(mark.amount_snapshot or 0),
                "hasPayoutQr": False,
                "markedPaid": False,
                "markedAt": None,
                "markedById": None,
                "markedByName": None,
                "markedAmountSnapshot": None,
            }
            self._hydrate_monthly_user_fields(session, item, int(mark.uploader_id))
            self._apply_monthly_mark(session, item, mark)
            grouped[int(mark.uploader_id)] = item

        items = sorted(
            grouped.values(),
            key=lambda item: (
                -int(item.get("payoutAmount") or 0),
                -int(item.get("paidDownloadCount") or 0),
                int(item.get("uploaderId") or 0),
            ),
        )
        return {
            "monthKey": month_key,
            "periodStart": month.replace(day=1).isoformat(),
            "periodEnd": (end_dt.date() - timedelta(days=1)).isoformat(),
            "totalPayoutAmount": sum(int(item.get("payoutAmount") or 0) for item in items),
            "totalPaidDownloadCount": sum(int(item.get("paidDownloadCount") or 0) for item in items),
            "creatorCount": len(items),
            "items": items,
        }

    def mark_monthly_payout(
        self,
        session: Session,
        *,
        month_key: str,
        uploader_id: int,
        mark_paid: bool,
        admin_id: int,
    ) -> dict[str, Any]:
        self._require_user(session, admin_id)
        self._require_user(session, uploader_id)
        overview = self.get_monthly_overview(session, month_key_raw=month_key)
        row = next((item for item in overview["items"] if int(item["uploaderId"]) == uploader_id), None)
        payout_amount = int((row or {}).get("payoutAmount") or 0)

        mark = self.finance_repo.find_monthly_payout_mark(session, month_key, uploader_id)
        if mark is None:
            mark = AdminMonthlyPayoutMarkRecord(month_key=month_key, uploader_id=uploader_id)
        mark.amount_snapshot = payout_amount
        mark.marked_by_id = admin_id
        mark.marked_at = datetime.now(UTC)
        mark.status = "PAID" if mark_paid else "PENDING"
        self.finance_repo.save_monthly_payout_mark(session, mark)
        session.commit()

        refreshed = self.get_monthly_overview(session, month_key_raw=month_key)
        target = next((item for item in refreshed["items"] if int(item["uploaderId"]) == uploader_id), None)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return target

    def get_admin_payout_qr(self, session: Session, *, uploader_id: int) -> dict[str, Any]:
        user = self._require_user(session, uploader_id)
        return {
            "uploaderId": uploader_id,
            "hasPayoutQr": bool(user.payout_qr_key),
            "payoutQrUrl": build_payout_qr_url(uploader_id, user.payout_qr_key),
        }

    def handle_gateway_notification(self, session: Session, params: dict[str, str]) -> str:
        parsed = self.transfer_provider.parse_gateway_notification(params)
        out_biz_no = parsed.out_biz_no
        status_value = parsed.status
        notification = AlipayGatewayNotificationRecord(
            biz_type=(params.get("biz_type") or "").strip() or None,
            out_biz_no=out_biz_no or None,
            status=status_value or None,
            event_id=parsed.event_id,
            notify_time=self._parse_notify_time(params.get("notify_time")),
            payload=str(params),
            sign_verified=parsed.sign_verified,
            processed=False,
        )
        if not out_biz_no:
            notification.process_result = "MISSING_OUT_BIZ_NO"
            self.finance_repo.save_gateway_notification(session, notification)
            session.commit()
            return self.transfer_provider.success_response_text()
        if not parsed.sign_verified:
            notification.process_result = "INVALID_SIGN"
            self.finance_repo.save_gateway_notification(session, notification)
            session.commit()
            return self.transfer_provider.success_response_text()

        transfer = self.finance_repo.find_transfer_by_out_biz_no(session, out_biz_no)
        if transfer is None:
            notification.process_result = "TRANSFER_NOT_FOUND"
            self.finance_repo.save_gateway_notification(session, notification)
            session.commit()
            return self.transfer_provider.success_response_text()

        self._apply_transfer_provider_result(
            session,
            transfer,
            TransferResult(
                status=status_value or TRANSFER_STATUS_PENDING,
                provider_name=self.transfer_provider.provider_name,
            ),
        )
        notification.processed = True
        notification.process_result = "OK"
        self.finance_repo.save_gateway_notification(session, notification)
        session.commit()
        return self.transfer_provider.success_response_text()

    def refresh_pending_transfers(self, session: Session) -> int:
        processed = 0
        for transfer in self.finance_repo.list_pending_transfers(session):
            self._apply_transfer_provider_result(session, transfer, self.transfer_provider.query_transfer(transfer))
            processed += 1
        session.commit()
        return processed

    def generate_pending_settlements(self, session: Session) -> int:
        threshold = datetime.now(UTC) - timedelta(days=max(1, self.settings.settlement_payout_delay_days))
        orders = self.finance_repo.list_paid_orders_eligible_for_settlement(session, threshold)
        created = 0
        for order in orders:
            if int(order.amount or 0) <= 0:
                continue
            if order.uploader_id is None:
                continue
            if self.finance_repo.find_settlement_by_source(session, "ORDER", order.id) is not None:
                continue
            paid_at = order.paid_at or order.created_at or datetime.now(UTC)
            settlement = SettlementRecord(
                order_id=order.id,
                material_id=order.material_id,
                material_title=order.material_title,
                uploader_id=order.uploader_id,
                gross_amount=int(order.amount or 0),
                platform_fee=int(order.platform_fee_amount or 0),
                payout_amount=int(order.creator_payable_amount or 0),
                status="PENDING",
                policy_version=order.policy_version or self.settings.settlement_policy_version,
                policy_id="MARKET",
                source_type="ORDER",
                source_id=order.id,
                scheduled_payout_at=paid_at + timedelta(days=max(1, self.settings.settlement_payout_delay_days)),
            )
            self.finance_repo.save_settlement(session, settlement)
            created += 1
        session.commit()
        return created

    def _ensure_transfer(
        self,
        session: Session,
        entity: CreatorPayoutApplicationRecord,
        *,
        amount_cents: int,
    ) -> PayoutTransferRecord:
        transfer = self.finance_repo.find_transfer_by_application(session, entity.id)
        if transfer is not None:
            return transfer
        transfer = PayoutTransferRecord(
            payout_application_id=entity.id,
            uploader_id=entity.user_id,
            out_biz_no=self.finance_repo.build_out_biz_no(),
            amount=amount_cents,
            payee_account=self._resolve_payee_account(entity),
            payee_name=self._resolve_payee_name(entity),
            status=TRANSFER_STATUS_SUBMITTED,
        )
        transfer = self.finance_repo.save_payout_transfer(session, transfer)
        self._apply_transfer_provider_result(session, transfer, self.transfer_provider.submit_transfer(transfer))
        return transfer

    def _apply_transfer_provider_result(self, session: Session, transfer: PayoutTransferRecord, result: TransferResult) -> None:
        normalized = (result.status or TRANSFER_STATUS_PENDING).strip().upper()
        transfer.alipay_order_id = result.alipay_order_id or transfer.alipay_order_id
        transfer.pay_fund_order_id = result.pay_fund_order_id or transfer.pay_fund_order_id
        if normalized == "SUCCESS":
            transfer.status = TRANSFER_STATUS_SUCCESS
            transfer.paid_at = transfer.paid_at or datetime.now(UTC)
            self.finance_repo.save_payout_transfer(session, transfer)
            self._settle_transfer(session, transfer)
            return
        if normalized in {"FAIL", TRANSFER_STATUS_FAILED}:
            transfer.status = TRANSFER_STATUS_FAILED
            transfer.failure_reason = result.failure_reason or transfer.failure_reason or "支付宝转账失败"
        elif normalized in {"SUBMITTED", TRANSFER_STATUS_SUBMITTED}:
            transfer.status = TRANSFER_STATUS_SUBMITTED
        else:
            transfer.status = TRANSFER_STATUS_PENDING
        self.finance_repo.save_payout_transfer(session, transfer)

    def _settle_transfer(self, session: Session, transfer: PayoutTransferRecord) -> None:
        application = self.finance_repo.get_payout_application(session, transfer.payout_application_id)
        if application is None:
            return
        application.status = PAYOUT_STATUS_SETTLED
        application.settled_at = transfer.paid_at or datetime.now(UTC)
        self.finance_repo.save_payout_application(session, application)

        now = datetime.now(UTC)
        for settlement in self.finance_repo.list_pending_due_settlements_for_uploader(session, application.user_id, now):
            settlement.status = "PAID"
            settlement.processed_at = now
            self.finance_repo.save_settlement(session, settlement)

        schedule = self.finance_repo.get_payout_schedule(session)
        if schedule is not None:
            today = datetime.now(SH_TZ).date()
            if schedule.last_payout_date is None or schedule.last_payout_date < today:
                schedule.last_payout_date = today
                self.finance_repo.save_payout_schedule(session, schedule)

    def _build_earnings(self, session: Session, user_id: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        settlements = self.finance_repo.list_settlements_for_uploader(session, user_id)
        gross = sum(int(item.gross_amount or 0) for item in settlements)
        platform_fee = sum(int(item.platform_fee or 0) for item in settlements)
        pending_total = sum(int(item.payout_amount or 0) for item in settlements if item.status == "PENDING")
        available = sum(
            int(item.payout_amount or 0)
            for item in settlements
            if item.status == "PENDING"
            and item.scheduled_payout_at is not None
            and self._normalize_dt(item.scheduled_payout_at) <= now
        )
        return {
            "grossAmount": gross,
            "platformFee": platform_fee,
            "payoutAmount": available,
            "orderCount": len(settlements),
            "unclaimedPayoutTotal": pending_total,
        }

    def _resolve_current_cycle(self, session: Session, *, allow_default: bool) -> dict[str, Any]:
        schedule = self.finance_repo.get_payout_schedule(session)
        if schedule is None or schedule.launch_date is None:
            if not allow_default:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先在后台配置上线日期/结算日")
            launch_date = datetime.now(SH_TZ).date()
            next_payout_date = launch_date + timedelta(days=7)
            return {
                "cycleKey": next_payout_date.isoformat(),
                "cycleStartDate": launch_date,
                "cycleEndDate": next_payout_date,
            }
        cycle_start = schedule.last_payout_date or schedule.launch_date
        cycle_end = schedule.next_payout_date or (cycle_start + timedelta(days=7))
        return {
            "cycleKey": cycle_end.isoformat(),
            "cycleStartDate": cycle_start,
            "cycleEndDate": cycle_end,
        }

    def _verify_kyc(
        self,
        session: Session,
        *,
        user_id: int,
        entity: CreatorPayoutApplicationRecord,
        real_name: str,
        id_card: str,
    ) -> dict[str, Any]:
        now = datetime.now(SH_TZ)
        try:
            id_hash = self.kyc_crypto_service.hash_id(id_card)
            id_last4 = self.kyc_crypto_service.last4(id_card)
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="实名核验配置缺失") from exc

        reuse = self.finance_repo.find_latest_verified_kyc(session, user_id)
        reuse_real_name = self._resolve_real_name_for_kyc_reuse(reuse)
        if reuse is not None and reuse.id_hash == id_hash and reuse_real_name == real_name and reuse.kyc_verified_at is not None:
            if self._normalize_dt(reuse.kyc_verified_at) >= datetime.now(UTC) - timedelta(days=max(1, self.settings.kyc_reuse_days)):
                return {
                    "kycStatus": KYC_STATUS_VERIFIED,
                    "verifiedAt": reuse.kyc_verified_at,
                    "provider": reuse.kyc_provider or "mock_local",
                    "requestId": reuse.kyc_request_id or f"KYCREUSE{user_id}",
                    "bizCode": reuse.kyc_biz_code or "REUSE",
                    "bizMessage": reuse.kyc_biz_message or "复用历史实名核验结果",
                    "idHash": id_hash,
                    "idLast4": id_last4,
                }

        attempt_date = entity.kyc_attempt_date
        attempt_count = int(entity.kyc_attempt_count or 0)
        today = now.date()
        if attempt_date != today:
            attempt_count = 0
            entity.kyc_attempt_date = today
        if attempt_count >= max(1, self.settings.kyc_max_attempts_per_day):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="今日核验次数已达上限")
        if entity.kyc_attempted_at is not None and attempt_count > 0:
            if self._normalize_dt(entity.kyc_attempted_at) >= datetime.now(UTC) - timedelta(seconds=max(10, self.settings.kyc_retry_cooldown_seconds)):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请稍后再试")
        entity.kyc_attempted_at = datetime.now(UTC)
        entity.kyc_attempt_count = attempt_count + 1

        if not self._looks_like_id_card(id_card):
            return {
                "kycStatus": KYC_STATUS_FAILED,
                "verifiedAt": None,
                "provider": self.kyc_provider.provider_name,
                "requestId": None,
                "bizCode": "INVALID_ID",
                "bizMessage": "身份证号格式不正确",
                "idHash": id_hash,
                "idLast4": id_last4,
            }
        decision = self.kyc_provider.verify_id2_meta(real_name=real_name, id_card_no=id_card)
        if decision.passed:
            return {
                "kycStatus": KYC_STATUS_VERIFIED,
                "verifiedAt": datetime.now(UTC),
                "provider": decision.provider_name,
                "requestId": decision.request_id,
                "bizCode": decision.biz_code,
                "bizMessage": decision.biz_message,
                "idHash": id_hash,
                "idLast4": id_last4,
            }
        if decision.retryable:
            return {
                "kycStatus": KYC_STATUS_PENDING,
                "verifiedAt": None,
                "provider": decision.provider_name,
                "requestId": decision.request_id,
                "bizCode": decision.biz_code,
                "bizMessage": decision.biz_message,
                "idHash": id_hash,
                "idLast4": id_last4,
            }
        return {
            "kycStatus": KYC_STATUS_FAILED,
            "verifiedAt": None,
            "provider": decision.provider_name,
            "requestId": decision.request_id,
            "bizCode": decision.biz_code,
            "bizMessage": decision.biz_message,
            "idHash": id_hash,
            "idLast4": id_last4,
        }

    def _to_application_payload(
        self,
        session: Session,
        entity: CreatorPayoutApplicationRecord,
        *,
        earnings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = self._require_user(session, entity.user_id)
        reviewer = self.auth_repo.find_user_by_id(session, entity.reviewer_id) if entity.reviewer_id is not None else None
        alipay_account = entity.alipay_account
        if alipay_account and "*" not in alipay_account and not entity.alipay_account_encrypted:
            alipay_account = self._mask_account(alipay_account)
        alipay_name = entity.alipay_name
        if alipay_name and "*" not in alipay_name and not entity.alipay_name_encrypted:
            alipay_name = self._mask_name(alipay_name)
        return {
            "id": entity.id,
            "status": entity.status,
            "alipayAccount": alipay_account,
            "alipayName": alipay_name,
            "contactType": entity.contact_type,
            "contactValue": entity.contact_value,
            "notes": entity.notes,
            "reviewNotes": entity.review_notes,
            "reviewerName": self._display_name(reviewer) if reviewer else None,
            "applicantName": self._display_name(user),
            "kycStatus": entity.kyc_status,
            "kycVerifiedAt": entity.kyc_verified_at.isoformat() if entity.kyc_verified_at else None,
            "cycleKey": entity.cycle_key,
            "cycleStartDate": entity.cycle_start_date.isoformat() if entity.cycle_start_date else None,
            "cycleEndDate": entity.cycle_end_date.isoformat() if entity.cycle_end_date else None,
            "createdAt": entity.created_at.isoformat() if entity.created_at else None,
            "updatedAt": entity.updated_at.isoformat() if entity.updated_at else None,
            "settledAt": entity.settled_at.isoformat() if entity.settled_at else None,
            "earnings": earnings or self._build_earnings(session, entity.user_id),
        }

    def _to_schedule_payload(self, entity: PayoutScheduleRecord) -> dict[str, Any]:
        recent_dates = self._compute_recent_dates(entity)
        return {
            "launchDate": entity.launch_date.isoformat() if entity.launch_date else None,
            "lastPayoutDate": entity.last_payout_date.isoformat() if entity.last_payout_date else None,
            "nextPayoutDate": entity.next_payout_date.isoformat() if entity.next_payout_date else None,
            "recentPayoutDates": [item.isoformat() for item in recent_dates],
        }

    def _to_settlement_detail(self, entity: SettlementRecord) -> dict[str, Any]:
        return {
            "settlementId": entity.id,
            "sourceType": entity.source_type,
            "sourceId": entity.source_id,
            "materialTitle": entity.material_title,
            "grossAmount": entity.gross_amount,
            "platformFee": entity.platform_fee,
            "payoutAmount": entity.payout_amount,
            "policyVersion": entity.policy_version,
            "scheduledPayoutAt": entity.scheduled_payout_at.isoformat() if entity.scheduled_payout_at else None,
            "createdAt": entity.created_at.isoformat() if entity.created_at else None,
            "status": entity.status,
        }

    def _hydrate_monthly_user_fields(self, session: Session, item: dict[str, Any], uploader_id: int) -> None:
        user = self.auth_repo.find_user_by_id(session, uploader_id)
        if user is None:
            item["uploaderUsername"] = item.get("uploaderUsername") or f"user-{uploader_id}"
            item["uploaderNickname"] = item.get("uploaderNickname")
            item["hasPayoutQr"] = False
            return
        item["uploaderUsername"] = user.username
        item["uploaderNickname"] = user.nickname
        item["hasPayoutQr"] = bool(user.payout_qr_key)

    def _apply_monthly_mark(
        self,
        session: Session,
        item: dict[str, Any],
        mark: AdminMonthlyPayoutMarkRecord | None,
    ) -> None:
        if mark is None:
            return
        item["markedPaid"] = mark.status.upper() == "PAID"
        item["markedAt"] = mark.marked_at.isoformat() if mark.marked_at else None
        item["markedById"] = mark.marked_by_id
        reviewer = self.auth_repo.find_user_by_id(session, mark.marked_by_id) if mark.marked_by_id is not None else None
        item["markedByName"] = self._display_name(reviewer) if reviewer else None
        item["markedAmountSnapshot"] = mark.amount_snapshot

    def _compute_recent_dates(self, entity: PayoutScheduleRecord) -> list[date]:
        result: list[date] = []
        launch = entity.launch_date
        next_date = entity.next_payout_date
        first_cycle = (launch + timedelta(days=7)) if launch is not None else None
        if next_date is not None:
            prev1 = next_date - timedelta(days=30)
            prev2 = next_date - timedelta(days=60)
            if first_cycle is not None and prev2 >= first_cycle:
                result.append(prev2)
            if first_cycle is not None and prev1 >= first_cycle:
                result.append(prev1)
            result.append(next_date)
        elif first_cycle is not None:
            result.extend([first_cycle, first_cycle + timedelta(days=30), first_cycle + timedelta(days=60)])
        if entity.last_payout_date is not None and entity.last_payout_date not in result:
            result.insert(0, entity.last_payout_date)
        return result[:3]

    def _looks_like_id_card(self, value: str) -> bool:
        return bool(re.fullmatch(r"\d{15}|\d{17}[\dX]", value))

    def _mask_account(self, value: str | None) -> str | None:
        if not value:
            return None
        return self.kyc_crypto_service.mask_account(value)

    def _mask_name(self, value: str | None) -> str | None:
        if not value:
            return None
        return self.kyc_crypto_service.mask_name(value)

    def _resolve_payee_account(self, entity: CreatorPayoutApplicationRecord) -> str | None:
        if entity.alipay_account_encrypted:
            try:
                return self.kyc_crypto_service.decrypt(entity.alipay_account_encrypted)
            except Exception:  # noqa: BLE001
                return entity.alipay_account
        return entity.alipay_account

    def _resolve_payee_name(self, entity: CreatorPayoutApplicationRecord) -> str | None:
        if entity.alipay_name_encrypted:
            try:
                return self.kyc_crypto_service.decrypt(entity.alipay_name_encrypted)
            except Exception:  # noqa: BLE001
                return entity.alipay_name
        return entity.alipay_name

    def _resolve_real_name_for_kyc_reuse(self, entity: CreatorPayoutApplicationRecord | None) -> str | None:
        if entity is None:
            return None
        if entity.real_name_encrypted:
            try:
                return self.kyc_crypto_service.decrypt(entity.real_name_encrypted)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _display_name(self, user: AuthUser | None) -> str | None:
        if user is None:
            return None
        return user.nickname or user.username

    def _require_user(self, session: Session, user_id: int) -> AuthUser:
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    def _account_payload(self, user: AuthUser) -> dict[str, Any]:
        grade_stages = [item for item in (user.grade_stages or "").split(",") if item]
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "signature": user.signature,
            "school": user.school,
            "college": user.college,
            "major": user.major,
            "gradeStages": grade_stages,
            "email": user.email,
            "emailPrivacy": bool(user.email_privacy),
            "avatar": user.avatar,
            "payoutQrUrl": build_payout_qr_url(user.id, user.payout_qr_key),
            "legendaryContributorUntil": user.legendary_contributor_until.isoformat() if user.legendary_contributor_until else None,
            "purchaseCount": 0,
            "saleCount": 0,
        }

    def _resolve_month(self, month_key_raw: str | None) -> date:
        if not month_key_raw:
            today = datetime.now(SH_TZ).date()
            return today.replace(day=1)
        try:
            year = int(month_key_raw[:4])
            month = int(month_key_raw[5:7])
            return date(year, month, 1)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="month 参数格式错误，应为 YYYY-MM") from exc

    def _parse_notify_time(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
            return parsed.replace(tzinfo=SH_TZ).astimezone(UTC)
        except Exception:  # noqa: BLE001
            return None

    def _normalize_dt(self, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
