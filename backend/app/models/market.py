from __future__ import annotations

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MarketItemRecord(TimestampMixin, Base):
    __tablename__ = "market_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    seller_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    seller_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="OTHER")
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_variant_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    images_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_variants_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    want_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    school: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="SALE")
    contact_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_value: Mapped[str | None] = mapped_column(Text, nullable=True)


class MarketWantRecord(TimestampMixin, Base):
    __tablename__ = "market_wants"
    __table_args__ = (UniqueConstraint("item_id", "user_id", name="uq_market_wants_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
