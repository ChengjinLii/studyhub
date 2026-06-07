from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.finance import (
    AdminMonthlyPayoutMarkRecord,
    AlipayGatewayNotificationRecord,
    CreatorPayoutApplicationRecord,
    OrderRecord,
    PaymentNotificationRecord,
    PaymentRecord,
    PayoutScheduleRecord,
    PayoutTransferRecord,
    SettlementRecord,
    WorkerLockRecord,
)


class FinanceRepository:
    def get_order(self, session: Session, order_id: int) -> OrderRecord | None:
        return session.get(OrderRecord, order_id)

    def find_order_by_out_trade_no(self, session: Session, out_trade_no: str) -> OrderRecord | None:
        stmt = select(OrderRecord).where(OrderRecord.out_trade_no == out_trade_no)
        return session.scalar(stmt)

    def find_latest_order_for_user_material(self, session: Session, user_id: int, material_id: int) -> OrderRecord | None:
        stmt = (
            select(OrderRecord)
            .where(OrderRecord.user_id == user_id, OrderRecord.material_id == material_id)
            .order_by(OrderRecord.created_at.desc(), OrderRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def list_paid_orders_between(self, session: Session, start: datetime, end: datetime) -> list[OrderRecord]:
        stmt = (
            select(OrderRecord)
            .where(
                OrderRecord.status == "PAID",
                OrderRecord.paid_at.is_not(None),
                OrderRecord.paid_at >= start,
                OrderRecord.paid_at < end,
            )
            .order_by(OrderRecord.paid_at.desc(), OrderRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def list_paid_orders_for_creator_between(self, session: Session, uploader_id: int, start: datetime, end: datetime) -> list[OrderRecord]:
        stmt = (
            select(OrderRecord)
            .where(
                OrderRecord.status == "PAID",
                OrderRecord.uploader_id == uploader_id,
                OrderRecord.paid_at.is_not(None),
                OrderRecord.paid_at >= start,
                OrderRecord.paid_at < end,
            )
            .order_by(OrderRecord.paid_at.desc(), OrderRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def list_paid_orders_eligible_for_settlement(self, session: Session, threshold: datetime) -> list[OrderRecord]:
        stmt = (
            select(OrderRecord)
            .where(
                OrderRecord.status == "PAID",
                OrderRecord.paid_at.is_not(None),
                OrderRecord.paid_at <= threshold,
            )
            .order_by(OrderRecord.paid_at.asc(), OrderRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def save_order(self, session: Session, entity: OrderRecord) -> OrderRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_payment_by_out_trade_no(self, session: Session, out_trade_no: str) -> PaymentRecord | None:
        stmt = select(PaymentRecord).where(PaymentRecord.out_trade_no == out_trade_no)
        return session.scalar(stmt)

    def find_latest_payment_by_order(self, session: Session, order_id: int) -> PaymentRecord | None:
        stmt = (
            select(PaymentRecord)
            .where(PaymentRecord.order_id == order_id)
            .order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def save_payment(self, session: Session, entity: PaymentRecord) -> PaymentRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def save_payment_notification(self, session: Session, entity: PaymentNotificationRecord) -> PaymentNotificationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_settlement_by_source(self, session: Session, source_type: str, source_id: int) -> SettlementRecord | None:
        stmt = select(SettlementRecord).where(SettlementRecord.source_type == source_type, SettlementRecord.source_id == source_id)
        return session.scalar(stmt)

    def list_settlements_for_uploader(self, session: Session, uploader_id: int) -> list[SettlementRecord]:
        stmt = (
            select(SettlementRecord)
            .where(SettlementRecord.uploader_id == uploader_id)
            .order_by(SettlementRecord.created_at.desc(), SettlementRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def list_pending_due_settlements_for_uploader(self, session: Session, uploader_id: int, now: datetime) -> list[SettlementRecord]:
        stmt = (
            select(SettlementRecord)
            .where(
                SettlementRecord.uploader_id == uploader_id,
                SettlementRecord.status == "PENDING",
                SettlementRecord.scheduled_payout_at.is_not(None),
                SettlementRecord.scheduled_payout_at <= now,
            )
            .order_by(SettlementRecord.created_at.asc(), SettlementRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def list_claimable_due_settlements_for_uploader(self, session: Session, uploader_id: int, now: datetime) -> list[SettlementRecord]:
        stmt = (
            select(SettlementRecord)
            .where(
                SettlementRecord.uploader_id == uploader_id,
                SettlementRecord.status == "PENDING",
                SettlementRecord.payout_transfer_id.is_(None),
                SettlementRecord.scheduled_payout_at.is_not(None),
                SettlementRecord.scheduled_payout_at <= now,
            )
            .order_by(SettlementRecord.created_at.asc(), SettlementRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def list_settlements_for_transfer(self, session: Session, transfer_id: int) -> list[SettlementRecord]:
        stmt = (
            select(SettlementRecord)
            .where(SettlementRecord.payout_transfer_id == transfer_id)
            .order_by(SettlementRecord.created_at.asc(), SettlementRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def list_pending_transfers(self, session: Session) -> list[PayoutTransferRecord]:
        stmt = (
            select(PayoutTransferRecord)
            .where(PayoutTransferRecord.status.in_(("SUBMITTED", "PENDING")))
            .order_by(PayoutTransferRecord.created_at.asc(), PayoutTransferRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def save_settlement(self, session: Session, entity: SettlementRecord) -> SettlementRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_payout_application(self, session: Session, application_id: int) -> CreatorPayoutApplicationRecord | None:
        return session.get(CreatorPayoutApplicationRecord, application_id)

    def find_latest_payout_application_for_user(self, session: Session, user_id: int) -> CreatorPayoutApplicationRecord | None:
        stmt = (
            select(CreatorPayoutApplicationRecord)
            .where(CreatorPayoutApplicationRecord.user_id == user_id)
            .order_by(CreatorPayoutApplicationRecord.created_at.desc(), CreatorPayoutApplicationRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def find_payout_application_by_user_cycle(self, session: Session, user_id: int, cycle_key: str) -> CreatorPayoutApplicationRecord | None:
        stmt = select(CreatorPayoutApplicationRecord).where(
            CreatorPayoutApplicationRecord.user_id == user_id,
            CreatorPayoutApplicationRecord.cycle_key == cycle_key,
        )
        return session.scalar(stmt)

    def find_latest_verified_kyc(self, session: Session, user_id: int) -> CreatorPayoutApplicationRecord | None:
        stmt = (
            select(CreatorPayoutApplicationRecord)
            .where(
                CreatorPayoutApplicationRecord.user_id == user_id,
                CreatorPayoutApplicationRecord.kyc_status == "VERIFIED",
                CreatorPayoutApplicationRecord.kyc_verified_at.is_not(None),
            )
            .order_by(CreatorPayoutApplicationRecord.kyc_verified_at.desc(), CreatorPayoutApplicationRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def list_payout_applications(self, session: Session, *, page: int, size: int) -> tuple[list[CreatorPayoutApplicationRecord], int]:
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        total = int(session.scalar(select(func.count()).select_from(CreatorPayoutApplicationRecord)) or 0)
        stmt = (
            select(CreatorPayoutApplicationRecord)
            .order_by(CreatorPayoutApplicationRecord.created_at.desc(), CreatorPayoutApplicationRecord.id.desc())
            .offset(safe_page * safe_size)
            .limit(safe_size)
        )
        return list(session.scalars(stmt)), total

    def save_payout_application(self, session: Session, entity: CreatorPayoutApplicationRecord) -> CreatorPayoutApplicationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_payout_transfer(self, session: Session, transfer_id: int) -> PayoutTransferRecord | None:
        return session.get(PayoutTransferRecord, transfer_id)

    def find_transfer_by_application(self, session: Session, payout_application_id: int) -> PayoutTransferRecord | None:
        stmt = select(PayoutTransferRecord).where(PayoutTransferRecord.payout_application_id == payout_application_id)
        return session.scalar(stmt)

    def find_transfer_by_out_biz_no(self, session: Session, out_biz_no: str) -> PayoutTransferRecord | None:
        stmt = select(PayoutTransferRecord).where(PayoutTransferRecord.out_biz_no == out_biz_no)
        return session.scalar(stmt)

    def save_payout_transfer(self, session: Session, entity: PayoutTransferRecord) -> PayoutTransferRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def save_gateway_notification(self, session: Session, entity: AlipayGatewayNotificationRecord) -> AlipayGatewayNotificationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_payout_schedule(self, session: Session) -> PayoutScheduleRecord | None:
        stmt = select(PayoutScheduleRecord).order_by(PayoutScheduleRecord.id.asc()).limit(1)
        return session.scalar(stmt)

    def save_payout_schedule(self, session: Session, entity: PayoutScheduleRecord) -> PayoutScheduleRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_monthly_payout_mark(self, session: Session, month_key: str, uploader_id: int) -> AdminMonthlyPayoutMarkRecord | None:
        stmt = select(AdminMonthlyPayoutMarkRecord).where(
            AdminMonthlyPayoutMarkRecord.month_key == month_key,
            AdminMonthlyPayoutMarkRecord.uploader_id == uploader_id,
        )
        return session.scalar(stmt)

    def list_monthly_payout_marks(self, session: Session, month_key: str) -> list[AdminMonthlyPayoutMarkRecord]:
        stmt = select(AdminMonthlyPayoutMarkRecord).where(AdminMonthlyPayoutMarkRecord.month_key == month_key)
        return list(session.scalars(stmt))

    def save_monthly_payout_mark(self, session: Session, entity: AdminMonthlyPayoutMarkRecord) -> AdminMonthlyPayoutMarkRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_worker_lock(self, session: Session, name: str) -> WorkerLockRecord | None:
        return session.get(WorkerLockRecord, name)

    def save_worker_lock(self, session: Session, entity: WorkerLockRecord) -> WorkerLockRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def build_out_trade_no(self) -> str:
        return "OD" + uuid.uuid4().hex[:24].upper()

    def build_trade_no(self) -> str:
        return "TRADE" + uuid.uuid4().hex[:20].upper()

    def build_out_biz_no(self) -> str:
        return "PT" + uuid.uuid4().hex[:24].upper()
