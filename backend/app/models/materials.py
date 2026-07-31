from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MaterialRecord(TimestampMixin, Base):
    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("uploader_id", "submission_key", name="uq_materials_uploader_submission_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    uploader_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    submission_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploader_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploader_nickname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    school: Mapped[str | None] = mapped_column(String(120), nullable=True)
    college: Mapped[str | None] = mapped_column(String(120), nullable=True)
    major: Mapped[str | None] = mapped_column(String(255), nullable=True)
    general_course: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    course_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grade_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grade_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_method: Mapped[str] = mapped_column(String(16), nullable=False, default="FILE")
    netdisk_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    netdisk_password: Mapped[str | None] = mapped_column(String(64), nullable=True)
    netdisk_expired_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    netdisk_reminder_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    preview_watermark_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preview_source: Mapped[str] = mapped_column(String(16), nullable=False, default="AUTO")
    preview_manifest: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    preview_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_preview_keys_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_preview_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_preview_images_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    copyright_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="VISIBLE")
    review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MaterialVersionRecord(TimestampMixin, Base):
    __tablename__ = "material_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)


class MaterialReviewRecord(TimestampMixin, Base):
    __tablename__ = "material_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaterialRatingRecord(TimestampMixin, Base):
    __tablename__ = "material_ratings"
    __table_args__ = (UniqueConstraint("material_id", "user_id", name="uq_material_ratings_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)


class MaterialLikeRecord(TimestampMixin, Base):
    __tablename__ = "material_likes"
    __table_args__ = (UniqueConstraint("material_id", "user_id", name="uq_material_likes_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class MaterialFavoriteRecord(TimestampMixin, Base):
    __tablename__ = "material_favorites"
    __table_args__ = (UniqueConstraint("material_id", "user_id", name="uq_material_favorites_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class MaterialViewRecord(TimestampMixin, Base):
    __tablename__ = "material_views"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    viewer_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class MaterialDownloadRecord(TimestampMixin, Base):
    __tablename__ = "material_downloads"
    __table_args__ = (UniqueConstraint("material_id", "user_id", name="uq_material_downloads_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class MaterialPurchaseRecord(TimestampMixin, Base):
    __tablename__ = "material_purchases"
    __table_args__ = (UniqueConstraint("material_id", "user_id", name="uq_material_purchases_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
