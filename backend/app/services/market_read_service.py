from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repos.auth_repo import AuthRepository
from app.repos.read_api_repo import ReadApiRepository
from app.services.read_support import parse_iso_datetime


class MarketReadService:
    def __init__(self, repo: ReadApiRepository, auth_repo: AuthRepository) -> None:
        self.repo = repo
        self.auth_repo = auth_repo

    def list_market(
        self,
        current_user_id: int | None,
        *,
        keyword: str | None,
        category: str | None,
        page: int,
        size: int,
    ) -> dict[str, Any]:
        seed = self.repo.load_seed()
        wanted_ids = set(self.get_wanted_ids(current_user_id)) if current_user_id is not None else set()
        items = [
            item
            for item in seed.get("marketItems", [])
            if item.get("status", "SALE") in {"SALE", "SOLD"} and self._matches(item, keyword, category)
        ]
        items.sort(key=lambda item: -parse_iso_datetime(item.get("createdAt")).timestamp())
        safe_page = max(page, 1)
        safe_size = max(1, min(size, 50))
        start = (safe_page - 1) * safe_size
        end = start + safe_size
        return {
            "items": [self._to_list_item(item, wanted_ids) for item in items[start:end]],
            "meta": {"page": safe_page, "size": safe_size, "total": len(items)},
            "stats": {
                "active": sum(1 for item in seed.get("marketItems", []) if item.get("status") == "SALE"),
                "sold": sum(1 for item in seed.get("marketItems", []) if item.get("status") == "SOLD"),
                "userCount": int(seed.get("stats", {}).get("users", len(seed.get("users", {})))),
            },
        }

    def get_wanted_ids(self, current_user_id: int | None) -> list[int]:
        if current_user_id is None:
            return []
        seed = self.repo.load_seed()
        return [int(item) for item in (seed.get("relationships") or {}).get("marketWanted", {}).get(str(current_user_id), [])]

    def get_detail(self, current_user_id: int | None, item_id: int) -> dict[str, Any]:
        seed = self.repo.load_seed()
        item = next((entry for entry in seed.get("marketItems", []) if int(entry["id"]) == item_id), None)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
        is_owner = current_user_id is not None and int(item.get("sellerId", 0)) == current_user_id
        if not is_owner and item.get("status") in {"REMOVED", "HIDDEN"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品已下架或已被删除")
        wanted_ids = set(self.get_wanted_ids(current_user_id))
        wanted = item_id in wanted_ids
        can_view_contact = is_owner or wanted
        return {
            "id": item["id"],
            "sellerId": item.get("sellerId"),
            "sellerName": item.get("sellerName"),
            "title": item.get("title"),
            "description": item.get("description"),
            "price": float(item.get("price", 0)),
            "category": item.get("category"),
            "images": list(item.get("images") or []),
            "imageVariants": list(item.get("imageVariants") or []),
            "wantCount": int(item.get("wantCount", 0)),
            "school": item.get("school"),
            "status": item.get("status"),
            "canViewContact": can_view_contact,
            "contactType": item.get("contactType") if can_view_contact else None,
            "contactValue": item.get("contactValue") if can_view_contact else None,
            "wanted": wanted,
            "isOwner": is_owner,
            "createdAt": item.get("createdAt"),
        }

    def _matches(self, item: dict[str, Any], keyword: str | None, category: str | None) -> bool:
        if keyword:
            haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
            if keyword.strip().lower() not in haystack:
                return False
        if category and item.get("category") != category:
            return False
        return True

    def _to_list_item(self, item: dict[str, Any], wanted_ids: set[int]) -> dict[str, Any]:
        return {
            "id": item["id"],
            "sellerId": item.get("sellerId"),
            "title": item["title"],
            "price": float(item.get("price", 0)),
            "category": item.get("category"),
            "thumbnail": item.get("thumbnail"),
            "thumbnailVariant": item.get("thumbnailVariant"),
            "wantCount": int(item.get("wantCount", 0)),
            "wanted": int(item["id"]) in wanted_ids if wanted_ids else False,
            "school": item.get("school"),
            "createdAt": item.get("createdAt"),
            "sellerName": item.get("sellerName"),
        }
