from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.market_asset_store import MarketAssetStore


THUMB_PROCESS = "image/resize,w_600/quality,q_75"
DETAIL_PROCESS = "image/resize,w_1400/quality,q_80"
THUMB_WIDTHS = (400, 800, 1200)
DETAIL_WIDTHS = (800, 1200, 1600)
THUMB_QUALITY = 75
DETAIL_QUALITY = 80
LQIP_PROCESS = "image/resize,w_24/quality,q_30"
MARKET_SIGNED_URL_TTL_SECONDS = 604800
PLACEHOLDER_IMAGE = "https://placehold.co/600x400?text=Campus+Market"


class LegacyMarketReadService:
    def __init__(self, settings: Settings, asset_store: MarketAssetStore) -> None:
        self.settings = settings
        self.asset_store = asset_store

    def list_market(
        self,
        session: Session,
        current_user_id: int | None,
        *,
        keyword: str | None,
        category: str | None,
        page: int,
        size: int,
    ) -> dict[str, Any]:
        safe_page = max(page, 1)
        safe_size = max(1, min(size, 50))
        offset = (safe_page - 1) * safe_size
        where_clauses = ["mi.status = 'SALE'"]
        params: dict[str, Any] = {"limit": safe_size, "offset": offset}
        if self._has_text(keyword):
            params["keyword"] = f"%{keyword.strip().lower()}%"
            where_clauses.append(
                "(LOWER(COALESCE(mi.title, '')) LIKE :keyword OR LOWER(COALESCE(mi.description, '')) LIKE :keyword)"
            )
        if self._has_text(category):
            params["category"] = category.strip().upper()
            where_clauses.append("UPPER(mi.category) = :category")

        count_sql = f"SELECT COUNT(*) FROM market_items mi WHERE {' AND '.join(where_clauses)}"
        total = int(session.execute(text(count_sql), params).scalar() or 0)
        list_sql = f"""
            SELECT
                mi.id,
                mi.seller_id,
                u.username AS seller_username,
                u.nickname AS seller_nickname,
                mi.title,
                mi.price,
                mi.category,
                mi.images_json,
                mi.want_count,
                mi.school,
                mi.created_at
            FROM market_items mi
            LEFT JOIN users u ON u.id = mi.seller_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY mi.created_at DESC, mi.id DESC
            LIMIT :limit OFFSET :offset
        """
        rows = [dict(row) for row in session.execute(text(list_sql), params).mappings().all()]
        item_ids = [int(row["id"]) for row in rows]
        wanted_ids = self._load_wanted_ids(session, current_user_id, item_ids)
        return {
            "items": [
                self._to_list_item(row, wanted=int(row["id"]) in wanted_ids)
                for row in rows
            ],
            "meta": {"page": safe_page, "size": safe_size, "total": total},
            "stats": self._load_market_stats(session),
        }

    def get_detail(self, session: Session, current_user_id: int | None, item_id: int) -> dict[str, Any]:
        row = session.execute(
            text(
                """
                SELECT
                    mi.id,
                    mi.seller_id,
                    u.username AS seller_username,
                    u.nickname AS seller_nickname,
                    mi.title,
                    mi.description,
                    mi.price,
                    mi.category,
                    mi.images_json,
                    mi.want_count,
                    mi.school,
                    mi.status,
                    mi.contact_type,
                    mi.contact_value,
                    mi.created_at
                FROM market_items mi
                LEFT JOIN users u ON u.id = mi.seller_id
                WHERE mi.id = :item_id
                LIMIT 1
                """
            ),
            {"item_id": item_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")

        is_owner = current_user_id is not None and int(row["seller_id"] or 0) == current_user_id
        if not is_owner and self._is_hidden_market_status(row["status"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品已下架或已被删除")

        wanted = item_id in self._load_wanted_ids(session, current_user_id, [item_id])
        can_view_contact = is_owner or wanted
        images = self._parse_images(row["images_json"])
        return {
            "id": int(row["id"]),
            "sellerId": self._as_int(row["seller_id"]),
            "sellerName": row["seller_nickname"],
            "title": row["title"] or "",
            "description": row["description"],
            "price": self._cents_to_price(row["price"]),
            "category": row["category"],
            "images": [self._build_detail_url(int(row["id"]), index + 1, key) for index, key in enumerate(images)],
            "imageVariants": [
                self._build_detail_variant(int(row["id"]), index + 1, key)
                for index, key in enumerate(images)
            ],
            "wantCount": self._as_int(row["want_count"]),
            "school": row["school"],
            "status": row["status"],
            "canViewContact": can_view_contact,
            "contactType": row["contact_type"] if can_view_contact else None,
            "contactValue": row["contact_value"] if can_view_contact else None,
            "wanted": wanted,
            "isOwner": is_owner,
            "createdAt": self._serialize_datetime(row["created_at"]),
        }

    def _load_market_stats(self, session: Session) -> dict[str, int]:
        active = int(session.execute(text("SELECT COUNT(*) FROM market_items WHERE status = 'SALE'")).scalar() or 0)
        sold = int(session.execute(text("SELECT COUNT(*) FROM market_items WHERE status = 'SOLD'")).scalar() or 0)
        user_count = int(session.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)
        return {"active": active, "sold": sold, "userCount": user_count}

    def _load_wanted_ids(self, session: Session, current_user_id: int | None, item_ids: list[int]) -> set[int]:
        if current_user_id is None or not item_ids:
            return set()
        stmt = text(
            """
            SELECT item_id
            FROM market_wants
            WHERE user_id = :user_id AND item_id IN :item_ids
            """
        ).bindparams(bindparam("item_ids", expanding=True))
        rows = session.execute(stmt, {"user_id": current_user_id, "item_ids": item_ids}).scalars().all()
        return {int(item_id) for item_id in rows}

    def _to_list_item(self, row: dict[str, Any], *, wanted: bool) -> dict[str, Any]:
        images = self._parse_images(row["images_json"])
        thumbnail_key = images[0] if images else PLACEHOLDER_IMAGE
        item_id = int(row["id"])
        return {
            "id": item_id,
            "sellerId": self._as_int(row["seller_id"]),
            "title": row["title"] or "",
            "price": self._cents_to_price(row["price"]),
            "category": row["category"],
            "thumbnail": self._build_thumb_url(item_id, 1, thumbnail_key),
            "thumbnailVariant": self._build_thumb_variant(item_id, 1, thumbnail_key),
            "wantCount": self._as_int(row["want_count"]),
            "wanted": wanted,
            "school": row["school"],
            "createdAt": self._serialize_datetime(row["created_at"]),
            "sellerName": row["seller_nickname"] or row["seller_username"],
        }

    def _build_thumb_url(self, item_id: int, index: int, key: str) -> str:
        return self._build_processed_url(item_id, index, key, THUMB_PROCESS)

    def _build_detail_url(self, item_id: int, index: int, key: str) -> str:
        return self._build_processed_url(item_id, index, key, DETAIL_PROCESS)

    def _build_thumb_variant(self, item_id: int, index: int, key: str) -> dict[str, Any]:
        if self._is_external_non_oss_url(key):
            return {"src": key, "srcSet": None, "webpSrcSet": None, "avifSrcSet": None, "lqip": None}
        return {
            "src": self._build_thumb_url(item_id, index, key),
            "srcSet": self._build_src_set(item_id, index, key, THUMB_WIDTHS, THUMB_QUALITY, None),
            "webpSrcSet": self._build_src_set(item_id, index, key, THUMB_WIDTHS, THUMB_QUALITY, "webp"),
            "avifSrcSet": self._build_src_set(item_id, index, key, THUMB_WIDTHS, THUMB_QUALITY, "avif"),
            "lqip": self._build_processed_url(item_id, index, key, LQIP_PROCESS),
        }

    def _build_detail_variant(self, item_id: int, index: int, key: str) -> dict[str, Any]:
        if self._is_external_non_oss_url(key):
            return {"src": key, "srcSet": None, "webpSrcSet": None, "avifSrcSet": None, "lqip": None}
        return {
            "src": self._build_detail_url(item_id, index, key),
            "srcSet": self._build_src_set(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, None),
            "webpSrcSet": self._build_src_set(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, "webp"),
            "avifSrcSet": self._build_src_set(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, "avif"),
            "lqip": self._build_processed_url(item_id, index, key, LQIP_PROCESS),
        }

    def _build_src_set(
        self,
        item_id: int,
        index: int,
        key: str,
        widths: tuple[int, ...],
        quality: int,
        image_format: str | None,
    ) -> str | None:
        variants = []
        for width in widths:
            process = self._build_process(width, quality, image_format)
            url = self._build_processed_url(item_id, index, key, process)
            if url:
                variants.append(f"{url} {width}w")
        return ", ".join(variants) or None

    def _build_process(self, width: int, quality: int, image_format: str | None) -> str:
        process = f"image/resize,w_{max(1, width)}/quality,q_{max(1, min(quality, 100))}"
        if image_format:
            process = f"{process}/format,{image_format}"
        return process

    def _build_processed_url(self, item_id: int, index: int, key: str, process: str | None) -> str:
        if self._is_external_non_oss_url(key):
            return key
        signed = self.asset_store.storage_provider.build_signed_object_url(
            root=self.asset_store.root,
            key=key,
            ttl_seconds=MARKET_SIGNED_URL_TTL_SECONDS,
            process=process,
        )
        if signed is not None:
            return signed
        return self.asset_store.build_public_url(item_id=item_id, index=index, key=key)

    def _parse_images(self, raw_json: Any) -> list[str]:
        if raw_json is None:
            return []
        if isinstance(raw_json, list):
            return [str(item) for item in raw_json if str(item).strip()]
        if isinstance(raw_json, str):
            text_value = raw_json.strip()
            if not text_value:
                return []
            try:
                loaded = json.loads(text_value)
            except json.JSONDecodeError:
                return []
            if isinstance(loaded, list):
                return [str(item) for item in loaded if str(item).strip()]
        return []

    def _serialize_datetime(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            else:
                value = value.astimezone(UTC)
            return value.isoformat().replace("+00:00", "Z")
        return str(value)

    def _cents_to_price(self, value: Any) -> float:
        return round(self._as_int(value) / 100.0, 2)

    def _as_int(self, value: Any, default: int = 0) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _has_text(self, value: Any) -> bool:
        return value is not None and str(value).strip() != ""

    def _is_hidden_market_status(self, status_value: Any) -> bool:
        if status_value is None:
            return False
        return str(status_value).strip().lower() in {"removed", "hidden"}

    def _is_external_non_oss_url(self, key: str) -> bool:
        if not (key.startswith("http://") or key.startswith("https://")):
            return False
        public_base = (self.settings.oss_public_base_url or "").rstrip("/")
        endpoint = (self.settings.oss_endpoint or "").removeprefix("https://").removeprefix("http://")
        bucket_host = f"https://{self.settings.oss_bucket}.{endpoint}" if self.settings.oss_bucket and endpoint else ""
        if public_base and key.startswith(public_base + "/"):
            return False
        if bucket_host and key.startswith(bucket_host + "/"):
            return False
        if "aliyuncs.com" in key or "oss-" in key:
            return False
        return True
