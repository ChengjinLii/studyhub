from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RequestRecord(TimestampMixin, Base):
    __tablename__ = "material_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    requester_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    requester_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    course: Mapped[str | None] = mapped_column(String(80), nullable=True)
    keyword: Mapped[str | None] = mapped_column(Text, nullable=True)
    school: Mapped[str | None] = mapped_column(String(120), nullable=True)
    college: Mapped[str | None] = mapped_column(String(120), nullable=True)
    major: Mapped[str | None] = mapped_column(String(255), nullable=True)
    budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    funded_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    contribution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_contribution_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    urgency_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    creator_floor_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_requirement: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepted_response_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")


class RequestResponseRecord(TimestampMixin, Base):
    __tablename__ = "material_request_responses"
    __table_args__ = (UniqueConstraint("request_id", "responder_id", name="uq_request_responder_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    request_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    responder_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    responder_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RequestContributionRecord(TimestampMixin, Base):
    __tablename__ = "material_request_contributions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    request_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    contributor_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    contributor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    deadline_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    out_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pay_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    refund_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RequestPreviewViewRecord(TimestampMixin, Base):
    __tablename__ = "material_request_preview_views"
    __table_args__ = (UniqueConstraint("request_id", "response_id", "viewer_id", name="uq_request_preview_view"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    response_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    viewer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    loaded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RequestArbitrationRecord(TimestampMixin, Base):
    __tablename__ = "material_request_arbitrations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    request_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    response_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    requester_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    responder_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
