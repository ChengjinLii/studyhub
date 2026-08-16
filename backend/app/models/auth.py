from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AuthUser(TimestampMixin, Base):
    __tablename__ = "auth_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    role_mask: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    free_download_quota: Mapped[int | None] = mapped_column(Integer, nullable=True, default=200)
    email_privacy: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    school: Mapped[str | None] = mapped_column(String(128), nullable=True)
    college: Mapped[str | None] = mapped_column(String(128), nullable=True)
    major: Mapped[str | None] = mapped_column(String(128), nullable=True)
    grade_stages: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    legendary_contributor_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_event_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payout_qr_key: Mapped[str | None] = mapped_column(String(512), nullable=True)


class LegacyAuthUser(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    openid: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    unionid: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(191), unique=True, index=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_mask: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    free_download_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    email_privacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    signature: Mapped[str | None] = mapped_column(String(300), nullable=True)
    school: Mapped[str | None] = mapped_column(String(120), nullable=True)
    college: Mapped[str | None] = mapped_column(String(120), nullable=True)
    major: Mapped[str | None] = mapped_column(String(120), nullable=True)
    grade_stages: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legendary_contributor_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_event_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payout_qr_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_checkin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unique_downloaders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EmailVerification(TimestampMixin, Base):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AuthSessionStateRecord(TimestampMixin, Base):
    __tablename__ = "auth_session_states"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
