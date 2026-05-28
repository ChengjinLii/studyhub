from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.async_db import async_session_scope
from app.services.materials_query_support import (
    compat_extract_primary_major,
    compat_major_matches,
    compat_material_filter_parts,
    compat_material_order_clause,
    compat_normalize_major_selections,
    compat_recommendation_score,
    compat_sort_material_rows,
)
from app.services.read_support import (
    clamp_limit,
    compat_as_float,
    compat_as_int,
    compat_cents_to_price,
    compat_has_text,
    compat_is_external_non_oss_url,
    compat_json_list_loads,
    compat_normalize_text,
    compat_serialize_datetime,
    compat_timestamp,
    compat_to_bool,
)


VISIBLE_MATERIAL_STATUS_SQL = "(m.status IS NULL OR LOWER(m.status) NOT IN ('hidden', 'removed'))"


class MaterialsCompatMixin:
    def _compat_list_materials(
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
        profile = self._compat_load_user_profile(session, current_user_id)
        safe_page = max(page, 1)
        safe_size = max(1, min(size, 100))
        start = (safe_page - 1) * safe_size
        total = self._compat_count_material_rows(
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
        page_rows = self._compat_load_material_rows(
            session,
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
            sort=sort,
            profile=profile,
            limit=safe_size,
            offset=start,
        )
        material_ids = [int(row["id"]) for row in page_rows]
        tags_by_material = self._compat_load_tags_map(session, material_ids)
        comment_counts = self._compat_load_comment_counts(session, material_ids)
        return {
            "items": [
                self._compat_to_list_item(
                    row,
                    tags=tags_by_material.get(int(row["id"]), []),
                    comment_count=comment_counts.get(int(row["id"]), 0),
                )
                for row in page_rows
            ],
            "meta": {"page": safe_page, "size": safe_size, "total": total},
            "stats": self._compat_load_material_stats(session),
            "availableTags": self._compat_load_available_tags(session),
        }

    def _compat_get_recommendations(self, session: Session, current_user_id: int | None, limit: int | None) -> list[dict[str, Any]]:
        profile = self._compat_load_user_profile(session, current_user_id)
        safe_limit = clamp_limit(limit, max_value=100)
        sliced = self._compat_load_material_rows(
            session,
            keyword=None,
            school=None,
            college=None,
            major=None,
            tag=None,
            grade_value=None,
            course_category=None,
            price=None,
            sort="latest",
            profile=profile,
            limit=safe_limit or None,
            offset=0,
        )
        material_ids = [int(row["id"]) for row in sliced]
        tags_by_material = self._compat_load_tags_map(session, material_ids)
        comment_counts = self._compat_load_comment_counts(session, material_ids)
        return [
            self._compat_to_list_item(
                row,
                tags=tags_by_material.get(int(row["id"]), []),
                comment_count=comment_counts.get(int(row["id"]), 0),
            )
            for row in sliced
        ]

    def _compat_get_detail(self, session: Session, current_user_id: int | None, material_id: int, can_manage_all: bool) -> dict[str, Any]:
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
        if not (can_manage_all or is_owner) and self._compat_is_hidden_material(row["status"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

        tags = self._compat_load_tags_map(session, [material_id]).get(material_id, [])
        comment_count = self._compat_load_comment_counts(session, [material_id]).get(material_id, 0)
        versions = self._compat_load_versions(session, material_id)
        reviews = self._compat_load_reviews(session, material_id)

        favorited = False
        liked = False
        my_rating: int | None = None
        purchased = False
        if current_user_id is not None:
            favorited = self._compat_material_relation_exists(
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
            liked = self._compat_material_relation_exists(
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
            my_rating = self._compat_load_my_rating(session, material_id, current_user_id)
            purchased = self._compat_has_paid_access(session, material_id, current_user_id)

        has_file = self._compat_has_text(row["file_key"])
        has_netdisk = self._compat_has_text(row["netdisk_url"])
        netdisk_accessible = has_netdisk and (self._compat_to_bool(row["is_free"]) or purchased or can_manage_all or is_owner)
        custom_preview_images = (
            self._compat_build_custom_preview_urls(material_id, self._compat_json_loads(row["custom_preview_images"]))
            if current_user_id is not None
            else []
        )

        return {
            "id": int(row["id"]),
            "uploaderId": self._compat_as_int(row["uploader_id"]),
            "uploaderUsername": row["uploader_username"],
            "uploaderNickname": row["uploader_nickname"],
            "copyrightOwner": self._compat_normalize_text(row["keywords"]),
            "title": row["title"] or "",
            "description": row["description"] or "",
            "originalFilename": row["original_filename"],
            "fileType": row["file_type"],
            "hasFile": has_file,
            "fileSize": self._compat_as_int(row["file_size"], default=0),
            "price": self._compat_cents_to_price(row["price"]),
            "free": self._compat_to_bool(row["is_free"]),
            "school": row["school"],
            "college": row["college"],
            "major": row["major"],
            "generalEducation": self._compat_to_bool(row["is_general_education"]),
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
            "previewWatermarkEnabled": self._compat_to_bool(row["preview_watermark_enabled"], default=True),
            "previewSource": row["preview_source"] or "AUTO",
            "previewManifest": self._compat_serialize_preview_manifest(row["preview_manifest"]),
            "customPreviewText": row["custom_preview_text"] if current_user_id is not None else None,
            "customPreviewImages": custom_preview_images,
            "ratingAvg": self._compat_as_float(row["rating_avg"]),
            "ratingCount": self._compat_as_int(row["rating_count"]),
            "likeCount": self._compat_as_int(row["like_count"]),
            "commentCount": comment_count,
            "viewCount": self._compat_as_int(row["view_count"]),
            "downloadCount": self._compat_as_int(row["download_count"]),
            "salesCount": self._compat_as_int(row["sales_count"]),
            "favorited": favorited,
            "purchased": purchased,
            "liked": liked,
            "myRating": my_rating,
            "versions": versions,
            "reviews": reviews,
        }

    def _compat_load_material_rows(
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
        sort: str | None = None,
        profile: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        where_clauses, params = self._compat_material_filter_parts(
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
        )
        if where_clauses == ["1 = 0"]:
            return []
        order_sql, order_params, recommendation_score_sql = self._compat_material_order_clause(sort=sort, profile=profile)
        params.update(order_params)
        paging_sql = ""
        safe_limit = max(1, int(limit)) if limit is not None else None
        safe_offset = max(0, int(offset)) if offset is not None else None
        if safe_limit is not None:
            params["limit"] = safe_limit
            paging_sql = "\n            LIMIT :limit"
        if safe_offset is not None and safe_offset > 0:
            # MySQL requires LIMIT when OFFSET is present.
            if safe_limit is None:
                params["limit"] = 18446744073709551615
                paging_sql = "\n            LIMIT :limit"
            params["offset"] = safe_offset
            paging_sql += "\n            OFFSET :offset"

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
                m.netdisk_url,
                {recommendation_score_sql} AS recommendation_score
            FROM materials m
            LEFT JOIN users u ON u.id = m.uploader_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY {order_sql}
            {paging_sql}
        """
        rows = session.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def _compat_count_material_rows(
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
    ) -> int:
        where_clauses, params = self._compat_material_filter_parts(
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
        )
        if where_clauses == ["1 = 0"]:
            return 0
        total = session.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM materials m
                WHERE {' AND '.join(where_clauses)}
                """
            ),
            params,
        ).scalar()
        return int(total or 0)

    def _compat_material_filter_parts(
        self,
        *,
        keyword: str | None,
        school: str | None,
        college: str | None,
        major: str | None,
        tag: str | None,
        grade_value: str | None,
        course_category: str | None,
        price: str | None,
    ) -> tuple[list[str], dict[str, Any]]:
        return compat_material_filter_parts(
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
            visible_material_status_sql=VISIBLE_MATERIAL_STATUS_SQL,
        )

    def _compat_material_order_clause(self, *, sort: str | None, profile: dict[str, Any] | None) -> tuple[str, dict[str, Any], str]:
        return compat_material_order_clause(sort=sort, profile=profile)

    def _compat_load_user_profile(self, session: Session, user_id: int | None) -> dict[str, Any] | None:
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

    async def _compat_load_user_profile_async(self, session, user_id: int | None) -> dict[str, Any] | None:
        if user_id is None:
            return None
        row = (
            await session.execute(
                text(
                    """
                    SELECT school, college, major, grade_stages
                    FROM users
                    WHERE id = :user_id
                    LIMIT 1
                    """
                ),
                {"user_id": user_id},
            )
        ).mappings().first()
        if row is None:
            return None
        return dict(row)

    def _compat_sort_material_rows(self, rows: list[dict[str, Any]], *, sort: str, profile: dict[str, Any] | None) -> list[dict[str, Any]]:
        return compat_sort_material_rows(rows, sort=sort, profile=profile)

    def _compat_load_tags_map(self, session: Session, material_ids: list[int]) -> dict[int, list[str]]:
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
            if self._compat_has_text(row["tag"]):
                result.setdefault(material_id, []).append(str(row["tag"]))
        return result

    async def _compat_load_tags_map_async(self, session, material_ids: list[int]) -> dict[int, list[str]]:
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
        rows = (await session.execute(stmt, {"material_ids": material_ids})).mappings().all()
        result: dict[int, list[str]] = {material_id: [] for material_id in material_ids}
        for row in rows:
            material_id = int(row["material_id"])
            if self._compat_has_text(row["tag"]):
                result.setdefault(material_id, []).append(str(row["tag"]))
        return result

    def _compat_load_comment_counts(self, session: Session, material_ids: list[int]) -> dict[int, int]:
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

    async def _compat_load_comment_counts_async(self, session, material_ids: list[int]) -> dict[int, int]:
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
        rows = (await session.execute(stmt, {"material_ids": material_ids})).mappings().all()
        return {int(row["material_id"]): int(row["total"]) for row in rows}

    def _compat_load_material_stats(self, session: Session) -> dict[str, int]:
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

    async def _compat_load_material_stats_async(self, session) -> dict[str, int]:
        total_task = session.execute(text("SELECT COUNT(*) FROM materials"))
        free_task = session.execute(text("SELECT COUNT(*) FROM materials WHERE is_free = 1"))
        downloads_task = session.execute(text("SELECT COALESCE(SUM(download_count), 0) FROM materials"))
        users_task = session.execute(text("SELECT COUNT(*) FROM users"))
        total_result, free_result, downloads_result, users_result = await asyncio.gather(
            total_task,
            free_task,
            downloads_task,
            users_task,
        )
        return {
            "totalMaterials": int(total_result.scalar() or 0),
            "freeMaterials": int(free_result.scalar() or 0),
            "totalDownloads": int(downloads_result.scalar() or 0),
            "userCount": int(users_result.scalar() or 0),
        }

    def _compat_load_available_tags(self, session: Session, limit: int = 30) -> list[str]:
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
        return [str(row["tag"]) for row in rows if self._compat_has_text(row["tag"])]

    async def _compat_load_available_tags_async(self, session, limit: int = 30) -> list[str]:
        rows = (
            await session.execute(
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
            )
        ).mappings().all()
        return [str(row["tag"]) for row in rows if self._compat_has_text(row["tag"])]

    def _compat_load_versions(self, session: Session, material_id: int) -> list[dict[str, Any]]:
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
                "createdAt": self._compat_serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    async def _compat_load_versions_async(self, session, material_id: int) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, version_label, changelog, file_type, created_at
                    FROM material_versions
                    WHERE material_id = :material_id
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                {"material_id": material_id},
            )
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "versionLabel": row["version_label"],
                "changelog": row["changelog"],
                "fileType": row["file_type"],
                "createdAt": self._compat_serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    def _compat_load_reviews(self, session: Session, material_id: int) -> list[dict[str, Any]]:
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
                "rating": self._compat_as_int(row["rating"]),
                "comment": row["comment"],
                "createdAt": self._compat_serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    async def _compat_load_reviews_async(self, session, material_id: int) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, reviewer, rating, comment, created_at
                    FROM reviews
                    WHERE material_id = :material_id
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                {"material_id": material_id},
            )
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "reviewer": row["reviewer"],
                "rating": self._compat_as_int(row["rating"]),
                "comment": row["comment"],
                "createdAt": self._compat_serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    def _compat_material_relation_exists(self, session: Session, sql: str, material_id: int, user_id: int) -> bool:
        row = session.execute(text(sql), {"material_id": material_id, "user_id": user_id}).first()
        return row is not None

    async def _compat_material_relation_exists_async(self, session, sql: str, material_id: int, user_id: int) -> bool:
        row = (await session.execute(text(sql), {"material_id": material_id, "user_id": user_id})).first()
        return row is not None

    def _compat_load_my_rating(self, session: Session, material_id: int, user_id: int) -> int | None:
        try:
            rating_entity = self.material_repo.find_rating(session, material_id, user_id)
        except Exception:
            rating_entity = None
        if rating_entity is not None:
            return int(rating_entity.rating)
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

    async def _compat_load_my_rating_async(self, session, material_id: int, user_id: int) -> int | None:
        value = None
        try:
            value = (
                await session.execute(
                    text(
                        """
                        SELECT rating
                        FROM material_ratings
                        WHERE material_id = :material_id AND user_id = :user_id
                        LIMIT 1
                        """
                    ),
                    {"material_id": material_id, "user_id": user_id},
                )
            ).scalar()
        except Exception:
            value = None
        if value is None:
            value = (
                await session.execute(
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
                )
            ).scalar()
        return None if value is None else int(value)

    def _compat_has_paid_access(self, session: Session, material_id: int, user_id: int) -> bool:
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

    async def _compat_has_paid_access_async(self, session, material_id: int, user_id: int) -> bool:
        order_paid_task = session.execute(
            text(
                """
                SELECT 1
                FROM orders
                WHERE material_id = :material_id AND user_id = :user_id AND status = 'PAID'
                LIMIT 1
                """
            ),
            {"material_id": material_id, "user_id": user_id},
        )
        payment_paid_task = session.execute(
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
        )
        order_paid_result, payment_paid_result = await asyncio.gather(order_paid_task, payment_paid_task)
        if order_paid_result.first() is not None:
            return True
        return payment_paid_result.first() is not None

    def _compat_build_custom_preview_urls(self, material_id: int, keys: list[Any]) -> list[str]:
        urls: list[str] = []
        for raw_key in keys:
            key = str(raw_key).strip() if raw_key is not None else ""
            if not key:
                continue
            if self._compat_is_external_non_oss_url(key):
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

    async def _compat_build_custom_preview_urls_async(self, material_id: int, keys: list[Any]) -> list[str]:
        async def build_one(index: int, key: str) -> str:
            if self._compat_is_external_non_oss_url(key):
                return key
            signed = await self.asset_store.storage_provider.build_signed_object_url_async(
                root=self.settings.resolved_material_asset_dir,
                key=key,
                ttl_seconds=self.settings.material_signed_url_ttl_seconds,
            )
            if signed is not None:
                return signed
            return await self.asset_store.build_public_custom_preview_url_async(
                material_id=material_id,
                index=index,
                key=key,
            )

        cleaned_keys = []
        for raw_key in keys:
            key = str(raw_key).strip() if raw_key is not None else ""
            if key:
                cleaned_keys.append(key)
        if not cleaned_keys:
            return []
        return list(
            await asyncio.gather(
                *(build_one(index + 1, key) for index, key in enumerate(cleaned_keys))
            )
        )

    async def _compat_count_material_rows_async(
        self,
        session,
        *,
        keyword: str | None,
        school: str | None,
        college: str | None,
        major: str | None,
        tag: str | None,
        grade_value: str | None,
        course_category: str | None,
        price: str | None,
    ) -> int:
        where_clauses, params = self._compat_material_filter_parts(
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
        )
        if where_clauses == ["1 = 0"]:
            return 0
        total = (
            await session.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM materials m
                    WHERE {' AND '.join(where_clauses)}
                    """
                ),
                params,
            )
        ).scalar()
        return int(total or 0)

    async def _compat_load_material_rows_async(
        self,
        session,
        *,
        keyword: str | None,
        school: str | None,
        college: str | None,
        major: str | None,
        tag: str | None,
        grade_value: str | None,
        course_category: str | None,
        price: str | None,
        sort: str | None = None,
        profile: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        where_clauses, params = self._compat_material_filter_parts(
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
        )
        if where_clauses == ["1 = 0"]:
            return []
        order_sql, order_params, recommendation_score_sql = self._compat_material_order_clause(sort=sort, profile=profile)
        params.update(order_params)
        paging_sql = ""
        safe_limit = max(1, int(limit)) if limit is not None else None
        safe_offset = max(0, int(offset)) if offset is not None else None
        if safe_limit is not None:
            params["limit"] = safe_limit
            paging_sql = "\n            LIMIT :limit"
        if safe_offset is not None and safe_offset > 0:
            # MySQL requires LIMIT when OFFSET is present.
            if safe_limit is None:
                params["limit"] = 18446744073709551615
                paging_sql = "\n            LIMIT :limit"
            params["offset"] = safe_offset
            paging_sql += "\n            OFFSET :offset"
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        m.id,
                        m.uploader_id,
                        COALESCE(NULLIF(u.nickname, ''), u.username) AS uploader_nickname,
                        u.username AS uploader_username,
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
                        m.rating_avg,
                        m.rating_count,
                        m.like_count,
                        m.view_count,
                        m.download_count,
                        m.sales_count,
                        m.created_at,
                        {recommendation_score_sql} AS recommendation_score
                    FROM materials m
                    LEFT JOIN users u ON u.id = m.uploader_id
                    WHERE {' AND '.join(where_clauses)}
                    ORDER BY {order_sql}
                    {paging_sql}
                    """
                ),
                params,
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    async def _compat_load_material_detail_row_async(self, session, material_id: int) -> dict[str, Any]:
        row = (
            await session.execute(
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
            )
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        return dict(row)

    def _compat_to_list_item(self, row: dict[str, Any], *, tags: list[str], comment_count: int) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "uploaderId": self._compat_as_int(row["uploader_id"]),
            "title": row["title"] or "",
            "description": row["description"] or "",
            "price": self._compat_cents_to_price(row["price"]),
            "free": self._compat_to_bool(row["is_free"]),
            "school": row["school"],
            "college": row["college"],
            "major": row["major"],
            "generalEducation": self._compat_to_bool(row["is_general_education"]),
            "hasFile": self._compat_has_text(row["file_key"]),
            "hasNetdisk": self._compat_has_text(row["netdisk_url"]),
            "courseCategory": row["course_category"] or "MAJOR",
            "gradeType": row["grade_type"] or "UG",
            "gradeValue": row["grade_value"] or "",
            "tags": tags,
            "ratingAvg": self._compat_as_float(row["rating_avg"]),
            "ratingCount": self._compat_as_int(row["rating_count"]),
            "likeCount": self._compat_as_int(row["like_count"]),
            "commentCount": comment_count,
            "viewCount": self._compat_as_int(row["view_count"]),
            "downloadCount": self._compat_as_int(row["download_count"]),
            "salesCount": self._compat_as_int(row["sales_count"]),
            "createdAt": self._compat_serialize_datetime(row["created_at"]),
            "uploaderUsername": row["uploader_username"],
            "uploaderNickname": row["uploader_nickname"],
            "copyrightOwner": self._compat_normalize_text(row["keywords"]),
        }

    def _compat_recommendation_score(self, row: dict[str, Any], *, school: str | None, college: str | None, major: str | None) -> int:
        return compat_recommendation_score(row, school=school, college=college, major=major)

    def _compat_major_matches(self, stored: str, target: str) -> bool:
        return compat_major_matches(stored, target)

    def _compat_extract_primary_major(self, raw: Any) -> str | None:
        return compat_extract_primary_major(raw)

    def _compat_normalize_major_selections(self, raw: Any) -> list[str]:
        return compat_normalize_major_selections(raw)

    def _compat_serialize_preview_manifest(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _compat_serialize_datetime(self, value: Any) -> str | None:
        return compat_serialize_datetime(value)

    def _compat_created_timestamp(self, value: Any) -> float:
        return compat_timestamp(value)

    def _compat_json_loads(self, value: Any) -> list[Any]:
        return compat_json_list_loads(value)

    def _compat_cents_to_price(self, value: Any) -> float:
        return compat_cents_to_price(value)

    def _compat_as_int(self, value: Any, default: int = 0) -> int:
        return compat_as_int(value, default)

    def _compat_as_float(self, value: Any, default: float = 0.0) -> float:
        return compat_as_float(value, default)

    def _compat_to_bool(self, value: Any, default: bool = False) -> bool:
        return compat_to_bool(value, default)

    def _compat_normalize_text(self, value: Any) -> str | None:
        return compat_normalize_text(value)

    def _compat_has_text(self, value: Any) -> bool:
        return compat_has_text(value)

    def _compat_is_hidden_material(self, status_value: Any) -> bool:
        normalized = self._compat_normalize_text(status_value)
        return normalized is not None and normalized.lower() in {"hidden", "removed"}

    def _compat_is_external_non_oss_url(self, key: str) -> bool:
        return compat_is_external_non_oss_url(key, self.settings)
