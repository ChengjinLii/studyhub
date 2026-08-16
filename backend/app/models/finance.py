from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OrderRecord(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    uploader_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    material_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    pay_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    out_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    platform_fee_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creator_payable_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentRecord(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    out_trade_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentNotificationRecord(TimestampMixin, Base):
    __tablename__ = "payment_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    out_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    sign_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    processed: Mapped[bool] = mapped_column(nullable=False, default=False)
    process_result: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SettlementRecord(TimestampMixin, Base):
    __tablename__ = "settlements"
    __table_args__ = (UniqueConstraint("source_type", "source_id", name="uq_settlements_source"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    material_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploader_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    gross_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    platform_fee: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payout_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    payout_transfer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_payout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreatorPayoutApplicationRecord(TimestampMixin, Base):
    __tablename__ = "creator_payout_applications"
    __table_args__ = (UniqueConstraint("user_id", "cycle_key", name="uq_creator_payout_user_cycle"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    alipay_account: Mapped[str | None] = mapped_column(String(128), nullable=True)
    alipay_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alipay_account_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    alipay_name_encrypted: Mapped[str | None] = mapped_column(String(256), nullable=True)
    real_name_encrypted: Mapped[str | None] = mapped_column(String(256), nullable=True)
    id_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    id_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    contact_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    contact_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    kyc_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kyc_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kyc_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kyc_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kyc_biz_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kyc_biz_message: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kyc_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kyc_attempt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    kyc_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cycle_key: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    cycle_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cycle_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PayoutTransferRecord(TimestampMixin, Base):
    __tablename__ = "payout_transfers"
    __table_args__ = (UniqueConstraint("payout_application_id", name="uq_payout_transfers_application"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    payout_application_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    uploader_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    out_biz_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payee_account: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payee_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alipay_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pay_fund_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUBMITTED")
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlipayGatewayNotificationRecord(TimestampMixin, Base):
    __tablename__ = "alipay_gateway_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    out_biz_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    notify_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    sign_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    processed: Mapped[bool] = mapped_column(nullable=False, default=False)
    process_result: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PayoutScheduleRecord(TimestampMixin, Base):
    __tablename__ = "payout_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    launch_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_payout_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_payout_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class AdminMonthlyPayoutMarkRecord(TimestampMixin, Base):
    __tablename__ = "admin_monthly_payout_marks"
    __table_args__ = (UniqueConstraint("month_key", "uploader_id", name="uq_admin_monthly_payout_mark"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    month_key: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    uploader_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    marked_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WorkerLockRecord(Base):
    __tablename__ = "worker_locks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class FinanceInstructionRecord(TimestampMixin, Base):
    __tablename__ = "finance_instructions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    instruction_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
