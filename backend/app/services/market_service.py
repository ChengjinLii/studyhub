from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.async_db import async_session_scope
from app.core.config import Settings
from app.core.upload_validation import validate_image_upload
from app.integrations.market_asset_store import MarketAssetStore
from app.models.market import MarketItemRecord
from app.repos.auth_repo import AuthRepository
from app.repos.market_repo import MarketRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.market import (
    AdminMarketBatchDeletePayload,
    AdminMarketBatchUpdatePayload,
    MarketCreatePayload,
    MarketStatusPayload,
)
from app.services.read_support import (
    compat_as_int,
    compat_cents_to_price,
    compat_has_text,
    compat_is_external_non_oss_url,
    compat_json_list_loads,
    compat_serialize_datetime,
    count_users_with_seed_fallback,
    parse_iso_datetime,
    serialize_datetime,
)


CATEGORIES = {"BOOK", "DIGITAL", "LIFE", "SPORT", "OTHER"}
CONTACT_TYPES = {"QQ", "WECHAT", "PHONE"}
ADMIN_STATUSES = {"SALE", "RESERVED", "SOLD", "REMOVED", "HIDDEN"}
PLACEHOLDER_IMAGE = "https://placehold.co/600x400?text=Campus+Market"
THUMB_PROCESS = "image/resize,w_600/quality,q_75"
DETAIL_PROCESS = "image/resize,w_1400/quality,q_80"
THUMB_WIDTHS = (400, 800, 1200)
DETAIL_WIDTHS = (800, 1200, 1600)
THUMB_QUALITY = 75
DETAIL_QUALITY = 80
LQIP_PROCESS = "image/resize,w_24/quality,q_30"
MARKET_SIGNED_URL_TTL_SECONDS = 604800


class MarketService:
    def __init__(
        self,
        settings: Settings,
        read_repo: ReadApiRepository,
        auth_repo: AuthRepository,
        market_repo: MarketRepository,
        asset_store: MarketAssetStore,
    ) -> None:
        self.settings = settings
        self.read_repo = read_repo
        self.auth_repo = auth_repo
        self.market_repo = market_repo
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
        if self.settings.requires_private_env_file:
            return self._compat_list_market(
                session,
                current_user_id,
                keyword=keyword,
                category=category,
                page=page,
                size=size,
            )
        self._bootstrap(session)
        wanted_ids = set(self.get_wanted_ids(session, current_user_id)) if current_user_id is not None else set()
        all_items = self.market_repo.list_items(session)
        items = [item for item in all_items if item.status in {"SALE", "SOLD"} and self._matches(item, keyword, category)]
        items.sort(key=lambda item: -parse_iso_datetime(self._serialize_dt(item.created_at)).timestamp())
        safe_page = max(page, 1)
        safe_size = max(1, min(size, 50))
        start = (safe_page - 1) * safe_size
        end = start + safe_size
        return {
            "items": [self._to_list_item(item, item.id in wanted_ids) for item in items[start:end]],
            "meta": {"page": safe_page, "size": safe_size, "total": len(items)},
            "stats": {
                "active": sum(1 for item in all_items if item.status == "SALE"),
                "sold": sum(1 for item in all_items if item.status == "SOLD"),
                "userCount": self._user_count_with_seed_fallback(session),
            },
        }

    def get_wanted_ids(self, session: Session, current_user_id: int | None) -> list[int]:
        self._bootstrap(session)
        if current_user_id is None:
            return []
        return self.market_repo.wanted_ids_for_user(session, current_user_id)

    def _user_count_with_seed_fallback(self, session: Session) -> int:
        return count_users_with_seed_fallback(session, self.auth_repo, self.read_repo)

    def get_detail(self, session: Session, current_user_id: int | None, item_id: int) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_get_detail(session, current_user_id, item_id)
        self._bootstrap(session)
        item = self.market_repo.get_item(session, item_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
        is_owner = current_user_id is not None and item.seller_id == current_user_id
        if not is_owner and item.status in {"REMOVED", "HIDDEN"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品已下架或已被删除")
        wanted = current_user_id is not None and self.market_repo.find_want(session, item_id, current_user_id) is not None
        return self._to_detail_item(item, wanted=wanted, is_owner=is_owner)

    async def get_detail_async(self, session: Session, current_user_id: int | None, item_id: int) -> dict[str, Any]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(self.get_detail, session, current_user_id, item_id)

        row = await self._call_with_new_async_session(self._compat_load_market_detail_row_async, item_id)
        is_owner = current_user_id is not None and int(row["seller_id"] or 0) == current_user_id
        if not is_owner and self._compat_is_hidden_market_status(row["status"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品已下架或已被删除")
        wanted_task = self._call_with_new_async_session(self._compat_load_wanted_ids_async, current_user_id, [item_id])
        images = self._compat_parse_images(row["images_json"])
        image_urls_task = asyncio.gather(
            *(self._compat_build_detail_url_async(int(row["id"]), index + 1, key) for index, key in enumerate(images))
        )
        image_variants_task = asyncio.gather(
            *(self._compat_build_detail_variant_async(int(row["id"]), index + 1, key) for index, key in enumerate(images))
        )
        wanted_ids, image_urls, image_variants = await asyncio.gather(wanted_task, image_urls_task, image_variants_task)
        wanted = item_id in wanted_ids
        can_view_contact = is_owner or wanted
        return {
            "id": int(row["id"]),
            "sellerId": self._compat_as_int(row["seller_id"]),
            "sellerName": row["seller_nickname"],
            "title": row["title"] or "",
            "description": row["description"],
            "price": self._compat_cents_to_price(row["price"]),
            "category": row["category"],
            "images": image_urls,
            "imageVariants": image_variants,
            "wantCount": self._compat_as_int(row["want_count"]),
            "school": row["school"],
            "status": row["status"],
            "canViewContact": can_view_contact,
            "contactType": row["contact_type"] if can_view_contact else None,
            "contactValue": row["contact_value"] if can_view_contact else None,
            "wanted": wanted,
            "isOwner": is_owner,
            "createdAt": self._compat_serialize_datetime(row["created_at"]),
        }

    def create_item(self, session: Session, payload: MarketCreatePayload, images: list[UploadFile], seller_id: int) -> dict[str, Any]:
        seed = self._bootstrap(session)
        seller = self._require_user(session, seller_id)
        if len(images) > self.settings.market_max_images:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="最多上传 3 张图片")
        for file in images:
            validate_image_upload(
                file,
                settings=self.settings,
                max_size_bytes=self.settings.market_image_max_size_bytes,
                missing_detail="请上传有效的商品图片",
                invalid_type_detail="商品图片仅支持 PNG、JPG、WEBP、GIF、BMP、AVIF、HEIC、HEIF 格式",
                too_large_detail="商品图片不能超过 5MB",
            )
        item_id = self.market_repo.next_item_id(session, seed)
        keys = [self.asset_store.save_upload(item_id=item_id, upload=file) for file in images if getattr(file, "filename", None)]
        item = MarketItemRecord(
            id=item_id,
            source="local",
            seller_id=seller.id,
            seller_name=seller.nickname or seller.username,
            title=payload.title.strip(),
            description=self._strip(payload.description),
            price_cents=int(round(payload.price * 100)),
            category=self._normalize_category(payload.category),
            school=self._strip(payload.school),
            status="SALE",
            contact_type=self._normalize_contact_type(payload.contactType),
            contact_value=payload.contactValue.strip(),
        )
        self._assign_images(item, keys)
        self.market_repo.save_item(session, item)
        session.commit()
        return self._to_detail_item(item, wanted=False, is_owner=True)

    def want_item(self, session: Session, item_id: int, user_id: int) -> dict[str, Any]:
        self._bootstrap(session)
        item = self._require_item(session, item_id)
        self._ensure_sale_status(item)
        if item.seller_id == user_id:
            return self._sync_count_and_detail(session, item, wanted=True, is_owner=True)
        self._require_user(session, user_id)
        if self.market_repo.find_want(session, item_id, user_id) is None:
            self.market_repo.add_want(session, item_id=item_id, user_id=user_id)
        session.commit()
        return self._sync_count_and_detail(session, item, wanted=True, is_owner=False)

    def cancel_want_item(self, session: Session, item_id: int, user_id: int) -> dict[str, Any]:
        self._bootstrap(session)
        item = self._require_item(session, item_id)
        self._ensure_sale_status(item)
        if item.seller_id == user_id:
            return self._sync_count_and_detail(session, item, wanted=False, is_owner=True)
        entity = self.market_repo.find_want(session, item_id, user_id)
        if entity is not None:
            self.market_repo.remove_want(session, entity)
        session.commit()
        return self._sync_count_and_detail(session, item, wanted=False, is_owner=False)

    def update_status(self, session: Session, item_id: int, seller_id: int, payload: MarketStatusPayload) -> dict[str, Any]:
        self._bootstrap(session)
        item = self._require_item(session, item_id)
        if item.seller_id != seller_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权更新此商品")
        item.status = self._normalize_user_status(payload.status)
        self.market_repo.save_item(session, item)
        session.commit()
        return self._to_detail_item(item, wanted=True, is_owner=True)

    def delete_item(self, session: Session, item_id: int, seller_id: int) -> None:
        self._bootstrap(session)
        item = self._require_item(session, item_id)
        if item.seller_id != seller_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该商品")
        self._delete_item(session, item)
        session.commit()

    def remove_by_admin(self, session: Session, item_id: int) -> None:
        self._bootstrap(session)
        item = self._require_item(session, item_id)
        self._delete_item(session, item)
        session.commit()

    def list_for_admin(
        self,
        session: Session,
        *,
        page: int,
        size: int,
        keyword: str | None,
        category: str | None,
        status_value: str | None,
    ) -> dict[str, Any]:
        self._bootstrap(session)
        items = self.market_repo.list_items(session)
        normalized_category = self._normalize_category(category) if category else None
        normalized_status = self._normalize_admin_status(status_value) if status_value else None
        filtered = []
        for item in items:
            if keyword:
                haystack = f"{item.title} {item.description or ''}".lower()
                if keyword.strip().lower() not in haystack:
                    continue
            if normalized_category and item.category != normalized_category:
                continue
            if normalized_status and item.status != normalized_status:
                continue
            filtered.append(item)
        safe_page = max(page, 1)
        safe_size = max(1, min(size, 100))
        start = (safe_page - 1) * safe_size
        end = start + safe_size
        return {
            "items": [self._to_admin_item(item) for item in filtered[start:end]],
            "meta": {"page": safe_page, "size": safe_size, "total": len(filtered)},
        }

    def batch_update(self, session: Session, payload: AdminMarketBatchUpdatePayload) -> dict[str, Any]:
        self._bootstrap(session)
        has_update_field = any(
            value not in (None, "")
            for value in [payload.status, payload.category, payload.school, payload.contactType, payload.contactValue]
        )
        if not has_update_field:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少填写一个需要更新的字段")
        updated = 0
        missing_ids: list[int] = []
        for item_id in payload.itemIds:
            item = self.market_repo.get_item(session, item_id)
            if item is None:
                missing_ids.append(item_id)
                continue
            changed = False
            if payload.status:
                next_status = self._normalize_admin_status(payload.status)
                if item.status != next_status:
                    item.status = next_status
                    changed = True
            if payload.category:
                next_category = self._normalize_category(payload.category)
                if item.category != next_category:
                    item.category = next_category
                    changed = True
            if payload.school is not None:
                next_school = self._strip(payload.school)
                if item.school != next_school:
                    item.school = next_school
                    changed = True
            if payload.contactType:
                next_contact_type = self._normalize_contact_type(payload.contactType)
                if item.contact_type != next_contact_type:
                    item.contact_type = next_contact_type
                    changed = True
            if payload.contactValue is not None:
                next_contact_value = self._strip(payload.contactValue)
                if item.contact_value != next_contact_value:
                    item.contact_value = next_contact_value
                    changed = True
            if changed:
                self.market_repo.save_item(session, item)
                updated += 1
        session.commit()
        return {"updated": updated, "requested": len(payload.itemIds), "missingIds": missing_ids}

    def batch_delete(self, session: Session, payload: AdminMarketBatchDeletePayload) -> dict[str, Any]:
        self._bootstrap(session)
        deleted = 0
        failed_ids: list[int] = []
        for item_id in payload.itemIds:
            item = self.market_repo.get_item(session, item_id)
            if item is None:
                failed_ids.append(item_id)
                continue
            self._delete_item(session, item)
            deleted += 1
        session.commit()
        return {"deleted": deleted, "requested": len(payload.itemIds), "failedIds": failed_ids}

    def resolve_public_image(self, session: Session, item_id: int, index: int) -> tuple[MarketItemRecord, str]:
        self._bootstrap(session)
        item = self._require_item(session, item_id)
        keys = self._loads(item.images_json)
        if index < 1 or index > len(keys):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
        key = str(keys[index - 1])
        return item, key

    def _bootstrap(self, session: Session) -> dict[str, Any]:
        seed = self.read_repo.load_seed()
        self.market_repo.ensure_seed_bootstrap(session, seed)
        return seed

    def _require_user(self, session: Session, user_id: int):
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    def _require_item(self, session: Session, item_id: int) -> MarketItemRecord:
        item = self.market_repo.get_item(session, item_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
        return item

    def _ensure_sale_status(self, item: MarketItemRecord) -> None:
        if item.status != "SALE":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该商品已下架或已被删除")

    def _matches(self, item: MarketItemRecord, keyword: str | None, category: str | None) -> bool:
        if keyword:
            haystack = f"{item.title} {item.description or ''}".lower()
            if keyword.strip().lower() not in haystack:
                return False
        if category and item.category != self._normalize_category(category):
            return False
        return True

    def _normalize_category(self, raw: str | None) -> str:
        if not raw or not raw.strip():
            return "OTHER"
        normalized = raw.strip().upper()
        return normalized if normalized in CATEGORIES else "OTHER"

    def _normalize_contact_type(self, raw: str | None) -> str:
        if not raw or not raw.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="联系方式类型无效")
        normalized = raw.strip().upper()
        if normalized in {"微信", "WECHAT"}:
            normalized = "WECHAT"
        if normalized in {"手机号", "PHONE"}:
            normalized = "PHONE"
        if normalized not in CONTACT_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="联系方式仅支持 QQ / 微信 / 手机号")
        return normalized

    def _normalize_user_status(self, raw: str | None) -> str:
        normalized = (raw or "SALE").strip().upper()
        if normalized not in {"SALE", "SOLD"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态仅支持 SALE 或 SOLD")
        return normalized

    def _normalize_admin_status(self, raw: str | None) -> str:
        normalized = (raw or "SALE").strip().upper()
        if normalized not in ADMIN_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态仅支持 SALE / RESERVED / SOLD / REMOVED / HIDDEN")
        return normalized

    def _assign_images(self, item: MarketItemRecord, keys: list[str]) -> None:
        image_values = keys if keys else [PLACEHOLDER_IMAGE]
        image_urls = [self._public_image_url(item.id, index + 1, key) if not self._is_external_url(key) else key for index, key in enumerate(image_values)]
        image_variants = [
            {"src": url, "srcSet": None, "webpSrcSet": None, "avifSrcSet": None, "lqip": None}
            for url in image_urls
        ]
        item.images_json = json.dumps(image_values, ensure_ascii=False, separators=(",", ":"))
        item.image_variants_json = json.dumps(image_variants, ensure_ascii=False, separators=(",", ":"))
        item.thumbnail_url = image_urls[0]
        item.thumbnail_variant_json = json.dumps(image_variants[0], ensure_ascii=False, separators=(",", ":"))

    def _delete_item(self, session: Session, item: MarketItemRecord) -> None:
        for key in self._loads(item.images_json):
            if not self._is_external_url(str(key)):
                self.asset_store.delete_key(str(key))
        self.market_repo.delete_wants_by_item(session, item.id)
        self.market_repo.delete_item(session, item)

    def _sync_count_and_detail(self, session: Session, item: MarketItemRecord, *, wanted: bool, is_owner: bool) -> dict[str, Any]:
        item.want_count = self.market_repo.count_wants(session, item.id)
        self.market_repo.save_item(session, item)
        session.commit()
        return self._to_detail_item(item, wanted=wanted, is_owner=is_owner)

    def _public_image_url(self, item_id: int, index: int, key: str) -> str:
        if self._is_external_url(key):
            return key
        return self.asset_store.build_public_url(item_id=item_id, index=index, key=key)

    def _to_list_item(self, item: MarketItemRecord, wanted: bool) -> dict[str, Any]:
        return {
            "id": item.id,
            "sellerId": item.seller_id,
            "title": item.title,
            "price": item.price_cents / 100.0,
            "category": item.category,
            "thumbnail": item.thumbnail_url,
            "thumbnailVariant": self._loads_object(item.thumbnail_variant_json),
            "wantCount": int(item.want_count or 0),
            "wanted": wanted,
            "school": item.school,
            "createdAt": self._serialize_dt(item.created_at),
            "sellerName": item.seller_name,
        }

    def _to_detail_item(self, item: MarketItemRecord, *, wanted: bool, is_owner: bool) -> dict[str, Any]:
        can_view_contact = is_owner or wanted
        image_keys = self._loads(item.images_json)
        images = [self._public_image_url(item.id, index + 1, str(key)) for index, key in enumerate(image_keys)]
        return {
            "id": item.id,
            "sellerId": item.seller_id,
            "sellerName": item.seller_name,
            "title": item.title,
            "description": item.description,
            "price": item.price_cents / 100.0,
            "category": item.category,
            "images": images,
            "imageVariants": self._loads(item.image_variants_json),
            "wantCount": int(item.want_count or 0),
            "school": item.school,
            "status": item.status,
            "canViewContact": can_view_contact,
            "contactType": item.contact_type if can_view_contact else None,
            "contactValue": item.contact_value if can_view_contact else None,
            "wanted": wanted,
            "isOwner": is_owner,
            "createdAt": self._serialize_dt(item.created_at),
        }

    def _to_admin_item(self, item: MarketItemRecord) -> dict[str, Any]:
        return {
            "id": item.id,
            "title": item.title,
            "price": item.price_cents / 100.0,
            "priceText": f"¥{item.price_cents / 100.0:.2f}",
            "category": item.category,
            "status": item.status,
            "wantCount": int(item.want_count or 0),
            "school": item.school,
            "createdAt": self._serialize_dt(item.created_at),
            "sellerId": item.seller_id,
            "sellerName": item.seller_name,
            "contactType": item.contact_type,
            "contactValue": item.contact_value,
            "thumbnail": item.thumbnail_url,
        }

    def _loads(self, raw: str | None) -> list[Any]:
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:  # noqa: BLE001
            return []
        return value if isinstance(value, list) else []

    def _loads_object(self, raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
        return value if isinstance(value, dict) else None

    def _serialize_dt(self, value) -> str | None:
        return serialize_datetime(value)

    async def _call_with_new_async_session(self, loader, *args, **kwargs):
        async with async_session_scope() as session:
            return await loader(session, *args, **kwargs)

    def _strip(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _is_external_url(self, value: str) -> bool:
        return value.startswith("http://") or value.startswith("https://")

    def _compat_list_market(
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
        if self._compat_has_text(keyword):
            params["keyword"] = f"%{keyword.strip().lower()}%"
            where_clauses.append(
                "(LOWER(COALESCE(mi.title, '')) LIKE :keyword OR LOWER(COALESCE(mi.description, '')) LIKE :keyword)"
            )
        if self._compat_has_text(category):
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
        wanted_ids = self._compat_load_wanted_ids(session, current_user_id, item_ids)
        return {
            "items": [self._compat_to_list_item(row, wanted=int(row["id"]) in wanted_ids) for row in rows],
            "meta": {"page": safe_page, "size": safe_size, "total": total},
            "stats": self._compat_load_market_stats(session),
        }

    def _compat_get_detail(self, session: Session, current_user_id: int | None, item_id: int) -> dict[str, Any]:
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
        if not is_owner and self._compat_is_hidden_market_status(row["status"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品已下架或已被删除")

        wanted = item_id in self._compat_load_wanted_ids(session, current_user_id, [item_id])
        can_view_contact = is_owner or wanted
        images = self._compat_parse_images(row["images_json"])
        return {
            "id": int(row["id"]),
            "sellerId": self._compat_as_int(row["seller_id"]),
            "sellerName": row["seller_nickname"],
            "title": row["title"] or "",
            "description": row["description"],
            "price": self._compat_cents_to_price(row["price"]),
            "category": row["category"],
            "images": [self._compat_build_detail_url(int(row["id"]), index + 1, key) for index, key in enumerate(images)],
            "imageVariants": [self._compat_build_detail_variant(int(row["id"]), index + 1, key) for index, key in enumerate(images)],
            "wantCount": self._compat_as_int(row["want_count"]),
            "school": row["school"],
            "status": row["status"],
            "canViewContact": can_view_contact,
            "contactType": row["contact_type"] if can_view_contact else None,
            "contactValue": row["contact_value"] if can_view_contact else None,
            "wanted": wanted,
            "isOwner": is_owner,
            "createdAt": self._compat_serialize_datetime(row["created_at"]),
        }

    async def _compat_load_market_detail_row_async(self, session, item_id: int) -> dict[str, Any]:
        row = (
            await session.execute(
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
            )
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
        return dict(row)

    def _compat_load_market_stats(self, session: Session) -> dict[str, int]:
        active = int(session.execute(text("SELECT COUNT(*) FROM market_items WHERE status = 'SALE'")).scalar() or 0)
        sold = int(session.execute(text("SELECT COUNT(*) FROM market_items WHERE status = 'SOLD'")).scalar() or 0)
        user_count = int(session.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)
        return {"active": active, "sold": sold, "userCount": user_count}

    def _compat_load_wanted_ids(self, session: Session, current_user_id: int | None, item_ids: list[int]) -> set[int]:
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

    async def _compat_load_wanted_ids_async(self, session, current_user_id: int | None, item_ids: list[int]) -> set[int]:
        if current_user_id is None or not item_ids:
            return set()
        stmt = text(
            """
            SELECT item_id
            FROM market_wants
            WHERE user_id = :user_id AND item_id IN :item_ids
            """
        ).bindparams(bindparam("item_ids", expanding=True))
        rows = (await session.execute(stmt, {"user_id": current_user_id, "item_ids": item_ids})).scalars().all()
        return {int(item_id) for item_id in rows}

    def _compat_to_list_item(self, row: dict[str, Any], *, wanted: bool) -> dict[str, Any]:
        images = self._compat_parse_images(row["images_json"])
        thumbnail_key = images[0] if images else PLACEHOLDER_IMAGE
        item_id = int(row["id"])
        return {
            "id": item_id,
            "sellerId": self._compat_as_int(row["seller_id"]),
            "title": row["title"] or "",
            "price": self._compat_cents_to_price(row["price"]),
            "category": row["category"],
            "thumbnail": self._compat_build_thumb_url(item_id, 1, thumbnail_key),
            "thumbnailVariant": self._compat_build_thumb_variant(item_id, 1, thumbnail_key),
            "wantCount": self._compat_as_int(row["want_count"]),
            "wanted": wanted,
            "school": row["school"],
            "createdAt": self._compat_serialize_datetime(row["created_at"]),
            "sellerName": row["seller_nickname"] or row["seller_username"],
        }

    def _compat_build_thumb_url(self, item_id: int, index: int, key: str) -> str:
        return self._compat_build_processed_url(item_id, index, key, THUMB_PROCESS)

    def _compat_build_detail_url(self, item_id: int, index: int, key: str) -> str:
        return self._compat_build_processed_url(item_id, index, key, DETAIL_PROCESS)

    async def _compat_build_detail_url_async(self, item_id: int, index: int, key: str) -> str:
        return await self._compat_build_processed_url_async(item_id, index, key, DETAIL_PROCESS)

    def _compat_build_thumb_variant(self, item_id: int, index: int, key: str) -> dict[str, Any]:
        if self._compat_is_external_non_oss_url(key):
            return {"src": key, "srcSet": None, "webpSrcSet": None, "avifSrcSet": None, "lqip": None}
        return {
            "src": self._compat_build_thumb_url(item_id, index, key),
            "srcSet": self._compat_build_src_set(item_id, index, key, THUMB_WIDTHS, THUMB_QUALITY, None),
            "webpSrcSet": self._compat_build_src_set(item_id, index, key, THUMB_WIDTHS, THUMB_QUALITY, "webp"),
            "avifSrcSet": self._compat_build_src_set(item_id, index, key, THUMB_WIDTHS, THUMB_QUALITY, "avif"),
            "lqip": self._compat_build_processed_url(item_id, index, key, LQIP_PROCESS),
        }

    def _compat_build_detail_variant(self, item_id: int, index: int, key: str) -> dict[str, Any]:
        if self._compat_is_external_non_oss_url(key):
            return {"src": key, "srcSet": None, "webpSrcSet": None, "avifSrcSet": None, "lqip": None}
        return {
            "src": self._compat_build_detail_url(item_id, index, key),
            "srcSet": self._compat_build_src_set(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, None),
            "webpSrcSet": self._compat_build_src_set(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, "webp"),
            "avifSrcSet": self._compat_build_src_set(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, "avif"),
            "lqip": self._compat_build_processed_url(item_id, index, key, LQIP_PROCESS),
        }

    async def _compat_build_detail_variant_async(self, item_id: int, index: int, key: str) -> dict[str, Any]:
        if self._compat_is_external_non_oss_url(key):
            return {"src": key, "srcSet": None, "webpSrcSet": None, "avifSrcSet": None, "lqip": None}
        src_task = self._compat_build_detail_url_async(item_id, index, key)
        src_set_task = self._compat_build_src_set_async(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, None)
        webp_src_set_task = self._compat_build_src_set_async(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, "webp")
        avif_src_set_task = self._compat_build_src_set_async(item_id, index, key, DETAIL_WIDTHS, DETAIL_QUALITY, "avif")
        lqip_task = self._compat_build_processed_url_async(item_id, index, key, LQIP_PROCESS)
        src, src_set, webp_src_set, avif_src_set, lqip = await asyncio.gather(
            src_task,
            src_set_task,
            webp_src_set_task,
            avif_src_set_task,
            lqip_task,
        )
        return {
            "src": src,
            "srcSet": src_set,
            "webpSrcSet": webp_src_set,
            "avifSrcSet": avif_src_set,
            "lqip": lqip,
        }

    def _compat_build_src_set(
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
            process = self._compat_build_process(width, quality, image_format)
            url = self._compat_build_processed_url(item_id, index, key, process)
            if url:
                variants.append(f"{url} {width}w")
        return ", ".join(variants) or None

    async def _compat_build_src_set_async(
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
            process = self._compat_build_process(width, quality, image_format)
            url = await self._compat_build_processed_url_async(item_id, index, key, process)
            if url:
                variants.append(f"{url} {width}w")
        return ", ".join(variants) or None

    def _compat_build_process(self, width: int, quality: int, image_format: str | None) -> str:
        process = f"image/resize,w_{max(1, width)}/quality,q_{max(1, min(quality, 100))}"
        if image_format:
            process = f"{process}/format,{image_format}"
        return process

    def _compat_build_processed_url(self, item_id: int, index: int, key: str, process: str | None) -> str:
        if self._compat_is_external_non_oss_url(key):
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

    async def _compat_build_processed_url_async(self, item_id: int, index: int, key: str, process: str | None) -> str:
        if self._compat_is_external_non_oss_url(key):
            return key
        signed = await self.asset_store.storage_provider.build_signed_object_url_async(
            root=self.asset_store.root,
            key=key,
            ttl_seconds=MARKET_SIGNED_URL_TTL_SECONDS,
            process=process,
        )
        if signed is not None:
            return signed
        return await self.asset_store.build_public_url_async(item_id=item_id, index=index, key=key)

    def _compat_parse_images(self, raw_json: Any) -> list[str]:
        return [str(item) for item in compat_json_list_loads(raw_json) if str(item).strip()]

    def _compat_serialize_datetime(self, value: Any) -> str | None:
        return compat_serialize_datetime(value)

    def _compat_cents_to_price(self, value: Any) -> float:
        return compat_cents_to_price(value)

    def _compat_as_int(self, value: Any, default: int = 0) -> int:
        return compat_as_int(value, default)

    def _compat_has_text(self, value: Any) -> bool:
        return compat_has_text(value)

    def _compat_is_hidden_market_status(self, status_value: Any) -> bool:
        if status_value is None:
            return False
        return str(status_value).strip().lower() in {"removed", "hidden"}

    def _compat_is_external_non_oss_url(self, key: str) -> bool:
        return compat_is_external_non_oss_url(key, self.settings, treat_generic_oss_as_internal=True)
