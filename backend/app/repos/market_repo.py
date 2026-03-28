from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import MarketItemRecord, MarketWantRecord


class MarketRepository:
    def ensure_seed_bootstrap(self, session: Session, seed: dict[str, Any]) -> None:
        if not seed:
            return
        items = seed.get("marketItems") or []
        seed_count = int(session.scalar(select(func.count()).select_from(MarketItemRecord).where(MarketItemRecord.source == "seed")) or 0)
        if seed_count >= len(items) and seed_count > 0:
            return

        for item in items:
            item_id = int(item["id"])
            entity = session.get(MarketItemRecord, item_id)
            if entity is None:
                entity = MarketItemRecord(
                    id=item_id,
                    source="seed",
                    seller_id=int(item["sellerId"]) if item.get("sellerId") is not None else None,
                    seller_name=item.get("sellerName"),
                    title=item.get("title") or "",
                    description=item.get("description"),
                    price_cents=int(round(float(item.get("price", 0)) * 100)),
                    category=item.get("category") or "OTHER",
                    thumbnail_url=item.get("thumbnail"),
                    thumbnail_variant_json=self._json_dumps(item.get("thumbnailVariant")),
                    images_json=self._json_dumps(item.get("images") or []),
                    image_variants_json=self._json_dumps(item.get("imageVariants") or []),
                    want_count=int(item.get("wantCount", 0) or 0),
                    school=item.get("school"),
                    status=item.get("status") or "SALE",
                    contact_type=item.get("contactType"),
                    contact_value=item.get("contactValue"),
                    created_at=self._parse_datetime(item.get("createdAt")),
                    updated_at=self._parse_datetime(item.get("createdAt")),
                )
                session.add(entity)

        for user_id, item_ids in ((seed.get("relationships") or {}).get("marketWanted") or {}).items():
            for item_id in item_ids:
                if self.find_want(session, int(item_id), int(user_id)) is None:
                    session.add(MarketWantRecord(item_id=int(item_id), user_id=int(user_id)))
        session.flush()

    def list_items(self, session: Session) -> list[MarketItemRecord]:
        stmt = select(MarketItemRecord).order_by(MarketItemRecord.created_at.desc(), MarketItemRecord.id.desc())
        return list(session.scalars(stmt))

    def list_visible_items_for_seller(
        self,
        session: Session,
        seller_id: int,
        *,
        limit: int | None = None,
    ) -> list[MarketItemRecord]:
        stmt = (
            select(MarketItemRecord)
            .where(
                MarketItemRecord.seller_id == seller_id,
                MarketItemRecord.status.not_in(("REMOVED", "HIDDEN")),
            )
            .order_by(MarketItemRecord.want_count.desc(), MarketItemRecord.created_at.desc(), MarketItemRecord.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def count_visible_items_for_seller(self, session: Session, seller_id: int) -> int:
        stmt = select(func.count()).select_from(MarketItemRecord).where(
            MarketItemRecord.seller_id == seller_id,
            MarketItemRecord.status.not_in(("REMOVED", "HIDDEN")),
        )
        return int(session.scalar(stmt) or 0)

    def list_items_by_ids(self, session: Session, item_ids: list[int]) -> list[MarketItemRecord]:
        if not item_ids:
            return []
        stmt = select(MarketItemRecord).where(MarketItemRecord.id.in_(item_ids))
        return list(session.scalars(stmt))

    def get_item(self, session: Session, item_id: int) -> MarketItemRecord | None:
        return session.get(MarketItemRecord, item_id)

    def next_item_id(self, session: Session, seed: dict[str, Any]) -> int:
        seed_max = max((int(item["id"]) for item in seed.get("marketItems") or []), default=0)
        db_max = int(session.scalar(select(func.max(MarketItemRecord.id))) or 0)
        return max(seed_max, db_max) + 1

    def save_item(self, session: Session, entity: MarketItemRecord) -> MarketItemRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def delete_item(self, session: Session, entity: MarketItemRecord) -> None:
        session.delete(entity)

    def find_want(self, session: Session, item_id: int, user_id: int) -> MarketWantRecord | None:
        stmt = select(MarketWantRecord).where(MarketWantRecord.item_id == item_id, MarketWantRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_want(self, session: Session, *, item_id: int, user_id: int) -> MarketWantRecord:
        entity = MarketWantRecord(item_id=item_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_want(self, session: Session, entity: MarketWantRecord) -> None:
        session.delete(entity)

    def delete_wants_by_item(self, session: Session, item_id: int) -> None:
        for entity in list(session.scalars(select(MarketWantRecord).where(MarketWantRecord.item_id == item_id))):
            session.delete(entity)

    def count_wants(self, session: Session, item_id: int) -> int:
        stmt = select(func.count()).select_from(MarketWantRecord).where(MarketWantRecord.item_id == item_id)
        return int(session.scalar(stmt) or 0)

    def wanted_ids_for_user(self, session: Session, user_id: int) -> list[int]:
        stmt = select(MarketWantRecord.item_id).where(MarketWantRecord.user_id == user_id)
        return [int(value) for value in session.scalars(stmt)]

    def wants_for_seller(self, session: Session, seller_id: int) -> list[MarketWantRecord]:
        item_ids = select(MarketItemRecord.id).where(MarketItemRecord.seller_id == seller_id)
        stmt = select(MarketWantRecord).where(MarketWantRecord.item_id.in_(item_ids)).order_by(MarketWantRecord.created_at.desc(), MarketWantRecord.id.desc())
        return list(session.scalars(stmt))

    def _json_dumps(self, value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
