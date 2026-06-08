from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import bindparam, func, inspect, select, text
from sqlalchemy.orm import Session

from app.models.market import MarketItemRecord, MarketWantRecord


_TABLE_COLUMN_CACHE: dict[tuple[str, str], set[str]] = {}
_MARKET_ITEM_MAPPED_COLUMNS = tuple(MarketItemRecord.__table__.columns)


def _bind_cache_key(session: Session) -> str:
    bind = session.get_bind()
    try:
        url = bind.engine.url
        rendered = url.render_as_string(hide_password=True)
        if url.database in {None, ":memory:"}:
            return f"{rendered}:{id(bind)}"
        return rendered
    except Exception:
        return str(bind)


def _table_columns(session: Session, table_name: str) -> set[str]:
    cache_key = (_bind_cache_key(session), table_name)
    cached = _TABLE_COLUMN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    inspector = inspect(session.get_bind())
    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    _TABLE_COLUMN_CACHE[cache_key] = column_names
    return column_names


def _has_table_column(session: Session, table_name: str, column_name: str) -> bool:
    return column_name in _table_columns(session, table_name)


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class MarketRepository:
    def _uses_legacy_market_items(self, session: Session) -> bool:
        existing_columns = _table_columns(session, "market_items")
        return any(column.name not in existing_columns for column in _MARKET_ITEM_MAPPED_COLUMNS)

    def _uses_legacy_market_wants(self, session: Session) -> bool:
        return "market_wants" in inspect(session.get_bind()).get_table_names() and not _has_table_column(session, "market_wants", "updated_at")

    def ensure_seed_bootstrap(self, session: Session, seed: dict[str, Any]) -> None:
        if not seed:
            return
        if self._uses_legacy_market_items(session):
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
        if self._uses_legacy_market_items(session):
            rows = session.execute(
                text(
                    """
                    SELECT *
                    FROM market_items
                    ORDER BY created_at DESC, id DESC
                    """
                )
            ).mappings().all()
            return [self._legacy_market_item_record(row) for row in rows]
        stmt = select(MarketItemRecord).order_by(MarketItemRecord.created_at.desc(), MarketItemRecord.id.desc())
        return list(session.scalars(stmt))

    def list_visible_items_for_seller(
        self,
        session: Session,
        seller_id: int,
        *,
        limit: int | None = None,
    ) -> list[MarketItemRecord]:
        if self._uses_legacy_market_items(session):
            limit_sql = "LIMIT :limit" if limit is not None else ""
            params: dict[str, Any] = {"seller_id": seller_id}
            if limit is not None:
                params["limit"] = max(1, int(limit))
            rows = session.execute(
                text(
                    f"""
                    SELECT *
                    FROM market_items
                    WHERE seller_id = :seller_id
                      AND status NOT IN ('REMOVED', 'HIDDEN')
                    ORDER BY want_count DESC, created_at DESC, id DESC
                    {limit_sql}
                    """
                ),
                params,
            ).mappings().all()
            return [self._legacy_market_item_record(row) for row in rows]
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
        if self._uses_legacy_market_items(session):
            return int(
                session.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM market_items
                        WHERE seller_id = :seller_id
                          AND status NOT IN ('REMOVED', 'HIDDEN')
                        """
                    ),
                    {"seller_id": seller_id},
                ).scalar()
                or 0
            )
        stmt = select(func.count()).select_from(MarketItemRecord).where(
            MarketItemRecord.seller_id == seller_id,
            MarketItemRecord.status.not_in(("REMOVED", "HIDDEN")),
        )
        return int(session.scalar(stmt) or 0)

    def list_items_by_ids(self, session: Session, item_ids: list[int]) -> list[MarketItemRecord]:
        if not item_ids:
            return []
        if self._uses_legacy_market_items(session):
            stmt = text(
                """
                SELECT *
                FROM market_items
                WHERE id IN :item_ids
                """
            ).bindparams(bindparam("item_ids", expanding=True))
            rows = session.execute(stmt, {"item_ids": sorted(set(item_ids))}).mappings().all()
            return [self._legacy_market_item_record(row) for row in rows]
        stmt = select(MarketItemRecord).where(MarketItemRecord.id.in_(item_ids))
        return list(session.scalars(stmt))

    def get_item(self, session: Session, item_id: int) -> MarketItemRecord | None:
        if self._uses_legacy_market_items(session):
            row = session.execute(text("SELECT * FROM market_items WHERE id = :item_id LIMIT 1"), {"item_id": item_id}).mappings().first()
            return self._legacy_market_item_record(row) if row is not None else None
        return session.get(MarketItemRecord, item_id)

    def next_item_id(self, session: Session, seed: dict[str, Any]) -> int:
        seed_max = max((int(item["id"]) for item in seed.get("marketItems") or []), default=0)
        db_max = int(session.scalar(select(func.max(MarketItemRecord.id))) or 0)
        return max(seed_max, db_max) + 1

    def save_item(self, session: Session, entity: MarketItemRecord) -> MarketItemRecord:
        if self._uses_legacy_market_items(session):
            self._save_legacy_market_item(session, entity)
            return entity
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def delete_item(self, session: Session, entity: MarketItemRecord) -> None:
        if self._uses_legacy_market_items(session):
            session.execute(text("DELETE FROM market_items WHERE id = :item_id"), {"item_id": int(entity.id)})
            return
        session.delete(entity)

    def find_want(self, session: Session, item_id: int, user_id: int) -> MarketWantRecord | None:
        if self._uses_legacy_market_wants(session):
            row = session.execute(
                text(
                    """
                    SELECT id, item_id, user_id, created_at
                    FROM market_wants
                    WHERE item_id = :item_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"item_id": item_id, "user_id": user_id},
            ).mappings().first()
            return self._legacy_market_want_record(row) if row is not None else None
        stmt = select(MarketWantRecord).where(MarketWantRecord.item_id == item_id, MarketWantRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_want(self, session: Session, *, item_id: int, user_id: int) -> MarketWantRecord:
        if self._uses_legacy_market_wants(session):
            timestamp = datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO market_wants (item_id, user_id, created_at)
                    VALUES (:item_id, :user_id, :created_at)
                    """
                ),
                {"item_id": item_id, "user_id": user_id, "created_at": timestamp},
            )
            want_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return MarketWantRecord(
                id=want_id or None,
                item_id=item_id,
                user_id=user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        entity = MarketWantRecord(item_id=item_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_want(self, session: Session, entity: MarketWantRecord) -> None:
        if self._uses_legacy_market_wants(session):
            if entity.id is not None:
                session.execute(text("DELETE FROM market_wants WHERE id = :id"), {"id": int(entity.id)})
            else:
                session.execute(
                    text("DELETE FROM market_wants WHERE item_id = :item_id AND user_id = :user_id"),
                    {"item_id": int(entity.item_id), "user_id": int(entity.user_id)},
                )
            return
        session.delete(entity)

    def delete_wants_by_item(self, session: Session, item_id: int) -> None:
        if self._uses_legacy_market_wants(session):
            session.execute(text("DELETE FROM market_wants WHERE item_id = :item_id"), {"item_id": item_id})
            return
        for entity in list(session.scalars(select(MarketWantRecord).where(MarketWantRecord.item_id == item_id))):
            session.delete(entity)

    def count_wants(self, session: Session, item_id: int) -> int:
        stmt = select(func.count()).select_from(MarketWantRecord).where(MarketWantRecord.item_id == item_id)
        return int(session.scalar(stmt) or 0)

    def wanted_ids_for_user(self, session: Session, user_id: int) -> list[int]:
        stmt = select(MarketWantRecord.item_id).where(MarketWantRecord.user_id == user_id)
        return [int(value) for value in session.scalars(stmt)]

    def wanted_ids_for_user_in_items(self, session: Session, user_id: int, item_ids: list[int]) -> list[int]:
        if not item_ids:
            return []
        stmt = select(MarketWantRecord.item_id).where(
            MarketWantRecord.user_id == user_id,
            MarketWantRecord.item_id.in_(item_ids),
        )
        return [int(value) for value in session.scalars(stmt)]

    def wants_for_seller(self, session: Session, seller_id: int, *, limit: int | None = None) -> list[MarketWantRecord]:
        if self._uses_legacy_market_wants(session):
            limit_sql = "LIMIT :limit" if limit is not None else ""
            params: dict[str, Any] = {"seller_id": seller_id}
            if limit is not None:
                params["limit"] = max(1, int(limit))
            rows = session.execute(
                text(
                    f"""
                    SELECT mw.id, mw.item_id, mw.user_id, mw.created_at
                    FROM market_wants mw
                    WHERE mw.item_id IN (
                        SELECT mi.id
                        FROM market_items mi
                        WHERE mi.seller_id = :seller_id
                    )
                    ORDER BY mw.created_at DESC, mw.id DESC
                    {limit_sql}
                    """
                ),
                params,
            ).mappings().all()
            return [self._legacy_market_want_record(row) for row in rows]
        item_ids = select(MarketItemRecord.id).where(MarketItemRecord.seller_id == seller_id)
        stmt = select(MarketWantRecord).where(MarketWantRecord.item_id.in_(item_ids)).order_by(MarketWantRecord.created_at.desc(), MarketWantRecord.id.desc())
        if limit is not None:
            stmt = stmt.limit(max(1, int(limit)))
        return list(session.scalars(stmt))

    def _legacy_market_item_record(self, row) -> MarketItemRecord:
        raw = dict(row)
        created_at = raw.get("created_at")
        updated_at = raw.get("updated_at") or created_at
        price_cents = _as_int(raw.get("price_cents", raw.get("price", 0)))
        return MarketItemRecord(
            id=int(raw["id"]),
            source=raw.get("source") or "local",
            seller_id=None if raw.get("seller_id") is None else int(raw["seller_id"]),
            seller_name=raw.get("seller_name"),
            title=raw.get("title") or "",
            description=raw.get("description"),
            price_cents=price_cents,
            category=raw.get("category") or "OTHER",
            thumbnail_url=raw.get("thumbnail_url"),
            thumbnail_variant_json=raw.get("thumbnail_variant_json"),
            images_json=raw.get("images_json"),
            image_variants_json=raw.get("image_variants_json"),
            want_count=_as_int(raw.get("want_count")),
            school=raw.get("school"),
            status=raw.get("status") or "SALE",
            contact_type=raw.get("contact_type"),
            contact_value=raw.get("contact_value"),
            created_at=created_at,
            updated_at=updated_at,
        )

    def _legacy_market_want_record(self, row) -> MarketWantRecord:
        return MarketWantRecord(
            id=int(row["id"]),
            item_id=int(row["item_id"]),
            user_id=int(row["user_id"]),
            created_at=row["created_at"],
            updated_at=row["created_at"],
        )

    def _save_legacy_market_item(self, session: Session, entity: MarketItemRecord) -> None:
        existing_columns = _table_columns(session, "market_items")
        now = datetime.now(UTC)
        if entity.created_at is None:
            entity.created_at = now
        entity.updated_at = now
        values = {
            "id": int(entity.id),
            "seller_id": entity.seller_id,
            "title": entity.title,
            "description": entity.description,
            "price": int(entity.price_cents or 0),
            "price_cents": int(entity.price_cents or 0),
            "category": entity.category,
            "images_json": entity.images_json,
            "contact_type": entity.contact_type,
            "contact_value": entity.contact_value,
            "want_count": int(entity.want_count or 0),
            "status": entity.status,
            "school": entity.school,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "source": entity.source,
            "seller_name": entity.seller_name,
            "thumbnail_url": entity.thumbnail_url,
            "thumbnail_variant_json": entity.thumbnail_variant_json,
            "image_variants_json": entity.image_variants_json,
        }
        row_exists = session.execute(text("SELECT 1 FROM market_items WHERE id = :id LIMIT 1"), {"id": int(entity.id)}).first() is not None
        if row_exists:
            update_columns = [
                column
                for column in values
                if column in existing_columns and column not in {"id", "created_at"}
            ]
            assignments = ", ".join(f"{column} = :{column}" for column in update_columns)
            if assignments:
                session.execute(text(f"UPDATE market_items SET {assignments} WHERE id = :id"), {column: values[column] for column in ["id", *update_columns]})
            return
        insert_columns = [column for column in values if column in existing_columns]
        placeholders = ", ".join(f":{column}" for column in insert_columns)
        session.execute(
            text(f"INSERT INTO market_items ({', '.join(insert_columns)}) VALUES ({placeholders})"),
            {column: values[column] for column in insert_columns},
        )

    def _json_dumps(self, value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
