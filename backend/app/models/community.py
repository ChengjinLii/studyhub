from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FeedbackRecord(TimestampMixin, Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    page: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")


class VolunteerApplicationRecord(TimestampMixin, Base):
    __tablename__ = "volunteer_applications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    school_major_grade: Mapped[str] = mapped_column(String(255), nullable=False)
    skills_csv: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_commitment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    intro: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")


class NotificationRecord(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class BotSpeechConfigRecord(TimestampMixin, Base):
    __tablename__ = "bot_speech_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BotSpeechMessageRecord(TimestampMixin, Base):
    __tablename__ = "bot_speech_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message: Mapped[str] = mapped_column(String(120), nullable=False)
    display_style: Mapped[str] = mapped_column(String(24), nullable=False, default="STANDARD")
    display_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    updated_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ReportRecord(TimestampMixin, Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    reporter_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    admin_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
