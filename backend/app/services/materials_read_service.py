from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repos.auth_repo import AuthRepository
from app.repos.read_api_repo import ReadApiRepository
from app.services.materials_search import (
    material_mapping_matches_search,
    material_mapping_search_score,
    parse_material_search_query,
)
from app.services.read_support import clamp_limit, parse_iso_datetime, serialize_user_snapshot


class MaterialsReadService:
    def __init__(self, repo: ReadApiRepository, auth_repo: AuthRepository) -> None:
        self.repo = repo
        self.auth_repo = auth_repo

    def list_materials(
        self,
        session: Session,
        current_user_id: int | None,
        *,
        keyword: str | None,
        school: str | None,
        college: str | None,
        major: str | None,
        tag: str | None,
        grade_value: str | None,
        course_category: str | None,
        price: str | None,
        sort: str,
        page: int,
        size: int,
    ) -> dict[str, Any]:
        seed = self.repo.load_seed()
        current_user = self._resolve_current_user(session, current_user_id)
        items = [
            material
            for material in seed.get("materials", [])
            if material.get("status", "VISIBLE") not in {"REMOVED", "HIDDEN"}
        ]
        search_query = parse_material_search_query(keyword)
        items = [material for material in items if self._matches_material(material, search_query, school, college, major, tag, grade_value, course_category, price)]

        normalized_sort = (sort or "latest").strip().lower()
        if normalized_sort == "newest":
            items.sort(
                key=lambda material: (
                    -parse_iso_datetime(material.get("createdAt")).timestamp(),
                    -int(material.get("id") or 0),
                )
            )
        elif normalized_sort == "downloads":
            items.sort(
                key=lambda material: (
                    -(material.get("downloadCount") or 0),
                    -parse_iso_datetime(material.get("createdAt")).timestamp(),
                    -int(material.get("id") or 0),
                )
            )
        elif normalized_sort == "recent_downloads":
            items.sort(
                key=lambda material: (
                    -(material.get("recentDownloadCount") or 0),
                    -(material.get("downloadCount") or 0),
                    -parse_iso_datetime(material.get("createdAt")).timestamp(),
                    -int(material.get("id") or 0),
                )
            )
        elif normalized_sort == "price":
            items.sort(key=lambda material: (float(material.get("price", 0)), -parse_iso_datetime(material.get("createdAt")).timestamp()))
        elif search_query.has_terms:
            items.sort(
                key=lambda material: (
                    -material_mapping_search_score(material, search_query),
                    -self._recommendation_score(material, current_user),
                    -(material.get("downloadCount") or 0),
                    -parse_iso_datetime(material.get("createdAt")).timestamp(),
                )
            )
        else:
            items.sort(
                key=lambda material: (
                    -self._recommendation_score(material, current_user),
                    -(material.get("downloadCount") or 0),
                    -parse_iso_datetime(material.get("createdAt")).timestamp(),
                )
            )

        safe_page = max(page, 1)
        safe_size = max(1, min(size, 100))
        start = (safe_page - 1) * safe_size
        end = start + safe_size
        page_items = [self._to_list_item(material) for material in items[start:end]]

        available_tags = sorted({tag_name for material in seed.get("materials", []) for tag_name in material.get("tags", []) if tag_name})
        return {
            "items": page_items,
            "meta": {"page": safe_page, "size": safe_size, "total": len(items)},
            "stats": {
                "totalMaterials": int(seed.get("stats", {}).get("materials", len(seed.get("materials", [])))),
                "freeMaterials": sum(1 for material in seed.get("materials", []) if material.get("free")),
                "totalDownloads": sum(int(material.get("downloadCount", 0)) for material in seed.get("materials", [])),
                "userCount": int(seed.get("stats", {}).get("users", len(seed.get("users", {})))),
            },
            "availableTags": available_tags,
        }

    def get_recommendations(self, session: Session, current_user_id: int | None, limit: int | None) -> list[dict[str, Any]]:
        seed = self.repo.load_seed()
        current_user = self._resolve_current_user(session, current_user_id)
        items = [
            material
            for material in seed.get("materials", [])
            if material.get("status", "VISIBLE") not in {"REMOVED", "HIDDEN"}
        ]
        items.sort(
            key=lambda material: (
                -self._recommendation_score(material, current_user),
                -(material.get("downloadCount") or 0),
                -parse_iso_datetime(material.get("createdAt")).timestamp(),
            )
        )
        safe_limit = clamp_limit(limit, max_value=100)
        sliced = items[:safe_limit] if safe_limit else items
        return [self._to_list_item(material) for material in sliced]

    def get_detail(self, seed_user_id: int | None, material_id: int) -> dict[str, Any]:
        seed = self.repo.load_seed()
        material = next((item for item in seed.get("materials", []) if int(item["id"]) == material_id), None)
        if material is None or material.get("status", "VISIBLE") in {"REMOVED", "HIDDEN"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

        relationships = seed.get("relationships") or {}
        user_key = str(seed_user_id) if seed_user_id is not None else None
        purchased_ids = set((relationships.get("materialPurchases") or {}).get(user_key, [])) if user_key else set()
        liked_ids = set((relationships.get("materialLikes") or {}).get(user_key, [])) if user_key else set()
        favorited_ids = set((relationships.get("materialFavorites") or {}).get(user_key, [])) if user_key else set()
        ratings = (relationships.get("materialRatings") or {}).get(user_key, {}) if user_key else {}

        detail = dict(material)
        detail.update(
            {
                "purchased": material.get("free") or material_id in purchased_ids,
                "liked": material_id in liked_ids,
                "favorited": material_id in favorited_ids,
                "myRating": ratings.get(str(material_id)),
                "versions": list(material.get("versions") or []),
                "reviews": list(material.get("reviews") or []),
            }
        )
        detail.pop("status", None)
        return detail

    def _resolve_current_user(self, session: Session, current_user_id: int | None) -> dict[str, Any] | None:
        if current_user_id is None:
            return None
        seed = self.repo.load_seed()
        seed_user = (seed.get("users") or {}).get(str(current_user_id))
        auth_user = self.auth_repo.find_user_by_id(session, current_user_id)
        if seed_user is None and auth_user is None:
            return None
        return serialize_user_snapshot(seed_user, auth_user)

    def _matches_material(
        self,
        material: dict[str, Any],
        search_query,
        school: str | None,
        college: str | None,
        major: str | None,
        tag: str | None,
        grade_value: str | None,
        course_category: str | None,
        price: str | None,
    ) -> bool:
        if not material_mapping_matches_search(material, search_query):
            return False
        if school and material.get("school") != school:
            return False
        if college and material.get("college") != college:
            return False
        if major and material.get("major") != major:
            return False
        if tag and tag not in material.get("tags", []):
            return False
        if grade_value and material.get("gradeValue") != grade_value:
            return False
        if course_category and material.get("courseCategory") != course_category:
            return False
        normalized_price = (price or "").strip().lower()
        if normalized_price == "free" and not material.get("free"):
            return False
        if normalized_price == "paid" and material.get("free"):
            return False
        return True

    def _recommendation_score(self, material: dict[str, Any], current_user: dict[str, Any] | None) -> int:
        if current_user is None:
            return 0
        score = 0
        if current_user.get("school") and current_user.get("school") == material.get("school"):
            score += 4
        if current_user.get("college") and current_user.get("college") == material.get("college"):
            score += 3
        if current_user.get("major") and current_user.get("major") == material.get("major"):
            score += 5
        grade_stages = current_user.get("gradeStages") or []
        if material.get("gradeValue") and material.get("gradeValue") in grade_stages:
            score += 2
        if material.get("tags") and "经验分享" in material.get("tags", []):
            score += 1
        return score

    def _to_list_item(self, material: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": material["id"],
            "uploaderId": material.get("uploaderId"),
            "title": material.get("title"),
            "description": material.get("description"),
            "price": float(material.get("price", 0)),
            "free": bool(material.get("free")),
            "school": material.get("school"),
            "college": material.get("college"),
            "major": material.get("major"),
            "generalEducation": bool(material.get("generalEducation")),
            "hasFile": bool(material.get("hasFile")),
            "hasNetdisk": bool(material.get("hasNetdisk")),
            "courseCategory": material.get("courseCategory"),
            "gradeType": material.get("gradeType"),
            "gradeValue": material.get("gradeValue"),
            "tags": list(material.get("tags") or []),
            "previewWatermarkEnabled": material.get("previewWatermarkEnabled"),
            "previewSource": material.get("previewSource"),
            "ratingAvg": material.get("ratingAvg"),
            "ratingCount": material.get("ratingCount"),
            "likeCount": material.get("likeCount"),
            "commentCount": material.get("commentCount"),
            "viewCount": material.get("viewCount"),
            "downloadCount": material.get("downloadCount"),
            "salesCount": material.get("salesCount"),
            "createdAt": material.get("createdAt"),
            "uploaderUsername": material.get("uploaderUsername"),
            "uploaderNickname": material.get("uploaderNickname"),
            "copyrightOwner": material.get("copyrightOwner"),
        }
