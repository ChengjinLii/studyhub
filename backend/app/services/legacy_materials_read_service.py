from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.material_asset_store import MaterialAssetStore
from app.services.read_support import clamp_limit


VISIBLE_MATERIAL_STATUS_SQL = "(m.status IS NULL OR LOWER(m.status) NOT IN ('hidden', 'removed'))"
MAJOR_SPLIT_PATTERN = re.compile(r"[，,、/]+")


class LegacyMaterialsReadService:
    def __init__(self, settings: Settings, asset_store: MaterialAssetStore) -> None:
        self.settings = settings
        self.asset_store = asset_store

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
        rows = self._load_material_rows(
            session,
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
        )
        profile = self._load_user_profile(session, current_user_id)
        ordered = self._sort_material_rows(rows, sort=sort, profile=profile)
        safe_page = max(page, 1)
        safe_size = max(1, min(size, 100))
        start = (safe_page - 1) * safe_size
        end = start + safe_size
        page_rows = ordered[start:end]
        material_ids = [int(row["id"]) for row in page_rows]
        tags_by_material = self._load_tags_map(session, material_ids)
        comment_counts = self._load_comment_counts(session, material_ids)
        return {
            "items": [
                self._to_list_item(
                    row,
                    tags=tags_by_material.get(int(row["id"]), []),
                    comment_count=comment_counts.get(int(row["id"]), 0),
                )
                for row in page_rows
            ],
            "meta": {"page": safe_page, "size": safe_size, "total": len(rows)},
            "stats": self._load_material_stats(session),
            "availableTags": self._load_available_tags(session),
        }

    def get_recommendations(self, session: Session, current_user_id: int | None, limit: int | None) -> list[dict[str, Any]]:
        rows = self._load_material_rows(
            session,
            keyword=None,
            school=None,
            college=None,
            major=None,
            tag=None,
            grade_value=None,
            course_category=None,
            price=None,
        )
        profile = self._load_user_profile(session, current_user_id)
        ordered = self._sort_material_rows(rows, sort="latest", profile=profile)
        safe_limit = clamp_limit(limit, max_value=100)
        sliced = ordered[:safe_limit] if safe_limit else ordered
        material_ids = [int(row["id"]) for row in sliced]
        tags_by_material = self._load_tags_map(session, material_ids)
        comment_counts = self._load_comment_counts(session, material_ids)
        return [
            self._to_list_item(
                row,
                tags=tags_by_material.get(int(row["id"]), []),
                comment_count=comment_counts.get(int(row["id"]), 0),
            )
            for row in sliced
        ]

    def get_detail(self, session: Session, current_user_id: int | None, material_id: int, can_manage_all: bool) -> dict[str, Any]:
        row = session.execute(
            text(
                """
                SELECT
                    m.id,
                    m.uploader_id,
                    u.username AS uploader_username,
                    u.nickname AS uploader_nickname,
                    m.title,
                    m.description,
                    m.original_filename,
                    m.file_type,
                    m.file_size,
                    m.price,
                    m.is_free,
                    m.school,
                    m.college,
                    m.major,
                    m.is_general_education,
                    m.netdisk_url,
                    m.netdisk_password,
                    m.netdisk_expired_at,
                    m.netdisk_reminder_at,
                    m.course_category,
                    m.grade_type,
                    m.grade_value,
                    m.preview_watermark_enabled,
                    m.preview_source,
                    m.preview_manifest,
                    m.custom_preview_text,
                    m.custom_preview_images,
                    m.rating_avg,
                    m.rating_count,
                    m.like_count,
                    m.view_count,
                    m.download_count,
                    m.sales_count,
                    m.file_key,
                    m.keywords,
                    m.status
                FROM materials m
                LEFT JOIN users u ON u.id = m.uploader_id
                WHERE m.id = :material_id
                LIMIT 1
                """
            ),
            {"material_id": material_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

        is_owner = current_user_id is not None and int(row["uploader_id"] or 0) == current_user_id
        if not (can_manage_all or is_owner) and self._is_hidden_material(row["status"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

        tags = self._load_tags_map(session, [material_id]).get(material_id, [])
        comment_count = self._load_comment_counts(session, [material_id]).get(material_id, 0)
        versions = self._load_versions(session, material_id)
        reviews = self._load_reviews(session, material_id)

        favorited = False
        liked = False
        my_rating: int | None = None
        purchased = False
        if current_user_id is not None:
            favorited = self._material_relation_exists(
                session,
                """
                SELECT 1
                FROM favorites
                WHERE material_id = :material_id AND user_id = :user_id
                LIMIT 1
                """,
                material_id,
                current_user_id,
            )
            liked = self._material_relation_exists(
                session,
                """
                SELECT 1
                FROM material_likes
                WHERE material_id = :material_id AND user_id = :user_id
                LIMIT 1
                """,
                material_id,
                current_user_id,
            )
            my_rating = self._load_my_rating(session, material_id, current_user_id)
            purchased = self._has_paid_access(session, material_id, current_user_id)

        has_file = self._has_text(row["file_key"])
        has_netdisk = self._has_text(row["netdisk_url"])
        netdisk_accessible = has_netdisk and (self._to_bool(row["is_free"]) or purchased or can_manage_all or is_owner)
        custom_preview_images = (
            self._build_custom_preview_urls(material_id, self._json_loads(row["custom_preview_images"]))
            if current_user_id is not None
            else []
        )

        return {
            "id": int(row["id"]),
            "uploaderId": self._as_int(row["uploader_id"]),
            "uploaderUsername": row["uploader_username"],
            "uploaderNickname": row["uploader_nickname"],
            "copyrightOwner": self._normalize_text(row["keywords"]),
            "title": row["title"] or "",
            "description": row["description"] or "",
            "originalFilename": row["original_filename"],
            "fileType": row["file_type"],
            "hasFile": has_file,
            "fileSize": self._as_int(row["file_size"], default=0),
            "price": self._cents_to_price(row["price"]),
            "free": self._to_bool(row["is_free"]),
            "school": row["school"],
            "college": row["college"],
            "major": row["major"],
            "generalEducation": self._to_bool(row["is_general_education"]),
            "hasNetdisk": has_netdisk,
            "netdiskUrl": row["netdisk_url"] if netdisk_accessible else None,
            "netdiskPassword": row["netdisk_password"] if netdisk_accessible else None,
            "netdiskExpiredAt": row["netdisk_expired_at"].isoformat() if row["netdisk_expired_at"] is not None else None,
            "netdiskReminderAt": row["netdisk_reminder_at"].isoformat() if row["netdisk_reminder_at"] is not None else None,
            "netdiskAccessible": netdisk_accessible,
            "courseCategory": row["course_category"] or "MAJOR",
            "gradeType": row["grade_type"] or "UG",
            "gradeValue": row["grade_value"] or "",
            "tags": tags,
            "previewWatermarkEnabled": self._to_bool(row["preview_watermark_enabled"], default=True),
            "previewSource": row["preview_source"] or "AUTO",
            "previewManifest": self._serialize_preview_manifest(row["preview_manifest"]),
            "customPreviewText": row["custom_preview_text"] if current_user_id is not None else None,
            "customPreviewImages": custom_preview_images,
            "ratingAvg": self._as_float(row["rating_avg"]),
            "ratingCount": self._as_int(row["rating_count"]),
            "likeCount": self._as_int(row["like_count"]),
            "commentCount": comment_count,
            "viewCount": self._as_int(row["view_count"]),
            "downloadCount": self._as_int(row["download_count"]),
            "salesCount": self._as_int(row["sales_count"]),
            "favorited": favorited,
            "purchased": purchased,
            "liked": liked,
            "myRating": my_rating,
            "versions": versions,
            "reviews": reviews,
        }

    def _load_material_rows(
        self,
        session: Session,
        *,
        keyword: str | None,
        school: str | None,
        college: str | None,
        major: str | None,
        tag: str | None,
        grade_value: str | None,
        course_category: str | None,
        price: str | None,
    ) -> list[dict[str, Any]]:
        where_clauses = ["m.deleted_at IS NULL", VISIBLE_MATERIAL_STATUS_SQL]
        params: dict[str, Any] = {}
        if self._has_text(keyword):
            params["keyword"] = f"%{keyword.strip().lower()}%"
            where_clauses.append(
                "(LOWER(COALESCE(m.title, '')) LIKE :keyword OR LOWER(COALESCE(m.description, '')) LIKE :keyword OR LOWER(COALESCE(m.keywords, '')) LIKE :keyword)"
            )
        if self._has_text(school):
            params["school"] = school.strip()
            where_clauses.append("m.school = :school")
        if self._has_text(college):
            params["college"] = college.strip()
            where_clauses.append("m.college = :college")
        if self._has_text(major):
            normalized_major = self._extract_primary_major(major)
            if normalized_major is None:
                return []
            params["major_like"] = f"%{normalized_major}%"
            where_clauses.append("LOWER(COALESCE(m.major, '')) LIKE LOWER(:major_like)")
        if self._has_text(tag):
            params["tag"] = tag.strip().lower()
            where_clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM material_tags mt
                    WHERE mt.material_id = m.id
                      AND LOWER(mt.tag) = :tag
                )
                """
            )
        if self._has_text(grade_value):
            params["grade_value"] = grade_value.strip().lower()
            where_clauses.append("LOWER(COALESCE(m.grade_value, '')) = :grade_value")
        if self._has_text(course_category):
            params["course_category"] = course_category.strip().upper()
            where_clauses.append("UPPER(COALESCE(m.course_category, 'MAJOR')) = :course_category")
        if self._has_text(price):
            normalized_price = price.strip().lower()
            if normalized_price == "free":
                where_clauses.append("m.is_free = 1")
            elif normalized_price == "paid":
                where_clauses.append("m.is_free = 0")

        sql = f"""
            SELECT
                m.id,
                m.uploader_id,
                u.username AS uploader_username,
                u.nickname AS uploader_nickname,
                m.title,
                m.description,
                m.price,
                m.is_free,
                m.school,
                m.college,
                m.major,
                m.is_general_education,
                m.course_category,
                m.grade_type,
                m.grade_value,
                m.keywords,
                m.rating_avg,
                m.rating_count,
                m.like_count,
                m.view_count,
                m.download_count,
                m.sales_count,
                m.created_at,
                m.file_key,
                m.netdisk_url
            FROM materials m
            LEFT JOIN users u ON u.id = m.uploader_id
            WHERE {' AND '.join(where_clauses)}
        """
        rows = session.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def _load_user_profile(self, session: Session, user_id: int | None) -> dict[str, Any] | None:
        if user_id is None:
            return None
        row = session.execute(
            text(
                """
                SELECT school, college, major, grade_stages
                FROM users
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        if row is None:
            return None
        return dict(row)

    def _sort_material_rows(self, rows: list[dict[str, Any]], *, sort: str, profile: dict[str, Any] | None) -> list[dict[str, Any]]:
        ordered = list(rows)
        normalized_sort = (sort or "latest").strip().lower()
        if normalized_sort == "price":
            ordered.sort(
                key=lambda row: (
                    self._as_int(row["price"]),
                    self._created_timestamp(row["created_at"]),
                ),
                reverse=True,
            )
            return ordered
        if normalized_sort == "sales":
            ordered.sort(
                key=lambda row: (
                    self._as_int(row["sales_count"]),
                    self._created_timestamp(row["created_at"]),
                ),
                reverse=True,
            )
            return ordered

        school = self._normalize_text(profile.get("school")) if profile else None
        college = self._normalize_text(profile.get("college")) if profile else None
        major = self._extract_primary_major(profile.get("major")) if profile else None
        ordered.sort(
            key=lambda row: (
                self._recommendation_score(row, school=school, college=college, major=major),
                self._as_int(row["download_count"]),
                self._created_timestamp(row["created_at"]),
            ),
            reverse=True,
        )
        return ordered

    def _load_tags_map(self, session: Session, material_ids: list[int]) -> dict[int, list[str]]:
        if not material_ids:
            return {}
        stmt = text(
            """
            SELECT material_id, tag
            FROM material_tags
            WHERE material_id IN :material_ids
            ORDER BY id ASC
            """
        ).bindparams(bindparam("material_ids", expanding=True))
        rows = session.execute(stmt, {"material_ids": material_ids}).mappings().all()
        result: dict[int, list[str]] = {material_id: [] for material_id in material_ids}
        for row in rows:
            material_id = int(row["material_id"])
            if self._has_text(row["tag"]):
                result.setdefault(material_id, []).append(str(row["tag"]))
        return result

    def _load_comment_counts(self, session: Session, material_ids: list[int]) -> dict[int, int]:
        if not material_ids:
            return {}
        stmt = text(
            """
            SELECT material_id, COUNT(*) AS total
            FROM comments
            WHERE status = 'visible' AND material_id IN :material_ids
            GROUP BY material_id
            """
        ).bindparams(bindparam("material_ids", expanding=True))
        rows = session.execute(stmt, {"material_ids": material_ids}).mappings().all()
        return {int(row["material_id"]): int(row["total"]) for row in rows}

    def _load_material_stats(self, session: Session) -> dict[str, int]:
        total_materials = int(session.execute(text("SELECT COUNT(*) FROM materials")).scalar() or 0)
        free_materials = int(session.execute(text("SELECT COUNT(*) FROM materials WHERE is_free = 1")).scalar() or 0)
        total_downloads = int(session.execute(text("SELECT COALESCE(SUM(download_count), 0) FROM materials")).scalar() or 0)
        user_count = int(session.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)
        return {
            "totalMaterials": total_materials,
            "freeMaterials": free_materials,
            "totalDownloads": total_downloads,
            "userCount": user_count,
        }

    def _load_available_tags(self, session: Session, limit: int = 30) -> list[str]:
        rows = session.execute(
            text(
                """
                SELECT LOWER(tag) AS tag
                FROM material_tags
                WHERE tag IS NOT NULL AND tag <> ''
                GROUP BY LOWER(tag)
                ORDER BY COUNT(id) DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
        return [str(row["tag"]) for row in rows if self._has_text(row["tag"])]

    def _load_versions(self, session: Session, material_id: int) -> list[dict[str, Any]]:
        rows = session.execute(
            text(
                """
                SELECT id, version_label, changelog, file_type, created_at
                FROM material_versions
                WHERE material_id = :material_id
                ORDER BY created_at DESC, id DESC
                """
            ),
            {"material_id": material_id},
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "versionLabel": row["version_label"],
                "changelog": row["changelog"],
                "fileType": row["file_type"],
                "createdAt": self._serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    def _load_reviews(self, session: Session, material_id: int) -> list[dict[str, Any]]:
        rows = session.execute(
            text(
                """
                SELECT id, reviewer, rating, comment, created_at
                FROM reviews
                WHERE material_id = :material_id
                ORDER BY created_at DESC, id DESC
                """
            ),
            {"material_id": material_id},
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "reviewer": row["reviewer"],
                "rating": self._as_int(row["rating"]),
                "comment": row["comment"],
                "createdAt": self._serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    def _material_relation_exists(self, session: Session, sql: str, material_id: int, user_id: int) -> bool:
        row = session.execute(text(sql), {"material_id": material_id, "user_id": user_id}).first()
        return row is not None

    def _load_my_rating(self, session: Session, material_id: int, user_id: int) -> int | None:
        value = session.execute(
            text(
                """
                SELECT rating
                FROM reviews
                WHERE material_id = :material_id AND user_id = :user_id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"material_id": material_id, "user_id": user_id},
        ).scalar()
        return None if value is None else int(value)

    def _has_paid_access(self, session: Session, material_id: int, user_id: int) -> bool:
        order_paid = session.execute(
            text(
                """
                SELECT 1
                FROM orders
                WHERE material_id = :material_id AND user_id = :user_id AND status = 'PAID'
                LIMIT 1
                """
            ),
            {"material_id": material_id, "user_id": user_id},
        ).first()
        if order_paid is not None:
            return True
        payment_paid = session.execute(
            text(
                """
                SELECT 1
                FROM payments p
                JOIN orders o ON o.id = p.order_id
                WHERE o.material_id = :material_id
                  AND o.user_id = :user_id
                  AND p.status = 'PAID'
                LIMIT 1
                """
            ),
            {"material_id": material_id, "user_id": user_id},
        ).first()
        return payment_paid is not None

    def _build_custom_preview_urls(self, material_id: int, keys: list[Any]) -> list[str]:
        urls: list[str] = []
        for raw_key in keys:
            key = str(raw_key).strip() if raw_key is not None else ""
            if not key:
                continue
            if self._is_external_non_oss_url(key):
                urls.append(key)
                continue
            signed = self.asset_store.storage_provider.build_signed_object_url(
                root=self.settings.resolved_material_asset_dir,
                key=key,
                ttl_seconds=self.settings.material_signed_url_ttl_seconds,
            )
            if signed is not None:
                urls.append(signed)
                continue
            urls.append(self.asset_store.build_public_custom_preview_url(material_id=material_id, index=len(urls) + 1, key=key))
        return urls

    def _to_list_item(self, row: dict[str, Any], *, tags: list[str], comment_count: int) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "uploaderId": self._as_int(row["uploader_id"]),
            "title": row["title"] or "",
            "description": row["description"] or "",
            "price": self._cents_to_price(row["price"]),
            "free": self._to_bool(row["is_free"]),
            "school": row["school"],
            "college": row["college"],
            "major": row["major"],
            "generalEducation": self._to_bool(row["is_general_education"]),
            "hasFile": self._has_text(row["file_key"]),
            "hasNetdisk": self._has_text(row["netdisk_url"]),
            "courseCategory": row["course_category"] or "MAJOR",
            "gradeType": row["grade_type"] or "UG",
            "gradeValue": row["grade_value"] or "",
            "tags": tags,
            "ratingAvg": self._as_float(row["rating_avg"]),
            "ratingCount": self._as_int(row["rating_count"]),
            "likeCount": self._as_int(row["like_count"]),
            "commentCount": comment_count,
            "viewCount": self._as_int(row["view_count"]),
            "downloadCount": self._as_int(row["download_count"]),
            "salesCount": self._as_int(row["sales_count"]),
            "createdAt": self._serialize_datetime(row["created_at"]),
            "uploaderUsername": row["uploader_username"],
            "uploaderNickname": row["uploader_nickname"],
            "copyrightOwner": self._normalize_text(row["keywords"]),
        }

    def _recommendation_score(self, row: dict[str, Any], *, school: str | None, college: str | None, major: str | None) -> int:
        score = 0
        material_school = self._normalize_text(row["school"])
        material_college = self._normalize_text(row["college"])
        material_major = self._normalize_text(row["major"])
        if school and material_school and school != material_school:
            score -= 45
        if college and material_college and college != material_college:
            score -= 15
        if major and material_major and not self._major_matches(material_major, major):
            score -= 8
        return score

    def _major_matches(self, stored: str, target: str) -> bool:
        if not target:
            return False
        return target in self._normalize_major_selections(stored)

    def _extract_primary_major(self, raw: Any) -> str | None:
        selections = self._normalize_major_selections(raw)
        return selections[0] if selections else None

    def _normalize_major_selections(self, raw: Any) -> list[str]:
        value = self._normalize_text(raw)
        if not value:
            return []
        normalized = []
        seen: set[str] = set()
        for chunk in MAJOR_SPLIT_PATTERN.split(value):
            item = chunk.strip()
            if not item:
                continue
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized

    def _serialize_preview_manifest(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _serialize_datetime(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return value
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            else:
                value = value.astimezone(UTC)
            return value.isoformat().replace("+00:00", "Z")
        return str(value)

    def _created_timestamp(self, value: Any) -> float:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.timestamp()
        return 0.0

    def _json_loads(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            text_value = value.strip()
            if not text_value:
                return []
            try:
                loaded = json.loads(text_value)
            except json.JSONDecodeError:
                return []
            return loaded if isinstance(loaded, list) else []
        return []

    def _cents_to_price(self, value: Any) -> float:
        return round(self._as_int(value) / 100.0, 2)

    def _as_int(self, value: Any, default: int = 0) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _as_float(self, value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return default

    def _to_bool(self, value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)

    def _normalize_text(self, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _has_text(self, value: Any) -> bool:
        return self._normalize_text(value) is not None

    def _is_hidden_material(self, status_value: Any) -> bool:
        normalized = self._normalize_text(status_value)
        return normalized is not None and normalized.lower() in {"hidden", "removed"}

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
        return True
