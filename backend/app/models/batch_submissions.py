from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BatchSubmissionRecord(TimestampMixin, Base):
    __tablename__ = "batch_submissions"
    __table_args__ = (
        UniqueConstraint("uploader_id", "submission_key", name="uq_batch_submissions_uploader_submission_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uploader_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    submission_key: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_method: Mapped[str] = mapped_column(String(16), nullable=False)
    publication_intent: Mapped[str] = mapped_column(String(32), nullable=False)
    pricing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    netdisk_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    netdisk_password: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", server_default="DRAFT", index=True)


class BatchSubmissionItemRecord(Base):
    __tablename__ = "batch_submission_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    upload_token_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", server_default="PENDING", index=True)
    scan_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING", index=True)
    scan_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleanup_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class BatchPublicationRecord(TimestampMixin, Base):
    __tablename__ = "batch_publications"
    __table_args__ = (UniqueConstraint("publication_key", name="uq_batch_publications_publication_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    publication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    item_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    operator_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pricing_confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", server_default="PENDING", index=True)


class BatchAuditRecord(TimestampMixin, Base):
    __tablename__ = "batch_audits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    operator_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
