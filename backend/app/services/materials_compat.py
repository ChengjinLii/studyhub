from __future__ import annotations

import asyncio
import json
from threading import RLock
from time import monotonic
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, inspect, text
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
    def _compat_file_key_sql(self, session: Session, table_alias: str | None = "m") -> str:
        prefix = f"{table_alias}." if table_alias else ""
        try:
            bind = session.get_bind()
            if hasattr(bind, "sync_engine"):
                bind = bind.sync_engine
            columns = {column["name"] for column in inspect(bind).get_columns("materials")}
        except Exception:
            columns = {"file_key", "file_storage_key"}
        if "file_storage_key" in columns:
            return f"COALESCE({prefix}file_storage_key, {prefix}file_key) AS file_key"
        return f"{prefix}file_key"

    def invalidate_material_summary_cache(self) -> None:
        cache, lock = self._compat_summary_cache_state()
        with lock:
            cache.clear()

    def _compat_record_view(
        self,
        session: Session,
        material_id: int,
        user_id: int | None,
        can_manage_all: bool,
        viewer_token: str | None,
    ) -> int:
        del can_manage_all
        row = session.execute(
            text(
                f"""
                SELECT id, view_count
                FROM materials m
                WHERE m.id = :material_id
                  AND {VISIBLE_MATERIAL_STATUS_SQL}
                LIMIT 1
                """
            ),
            {"material_id": material_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

        current_view_count = int(row["view_count"] or 0)
        token_hash = self._hash_viewer_token(viewer_token)
        if user_id is not None:
            existing = self.material_repo.find_view_by_user(session, material_id, user_id)
            if existing is not None:
                return current_view_count
            if token_hash:
                existing_by_token = self.material_repo.find_view_by_token_hash(session, material_id, token_hash)
                if existing_by_token is not None:
                    if existing_by_token.user_id is None:
                        self.material_repo.bind_view_to_user(session, existing_by_token, user_id)
                        session.commit()
                    return current_view_count
            self.material_repo.add_view(session, material_id=material_id, user_id=user_id, viewer_token_hash=token_hash)
        elif token_hash:
            if self.material_repo.find_view_by_token_hash(session, material_id, token_hash) is not None:
                return current_view_count
            self.material_repo.add_view(session, material_id=material_id, user_id=None, viewer_token_hash=token_hash)
        else:
            return current_view_count

        next_view_count = current_view_count + 1
        session.execute(
            text("UPDATE materials SET view_count = :view_count WHERE id = :material_id"),
            {"material_id": material_id, "view_count": next_view_count},
        )
        session.commit()
        return next_view_count

    def _compat_summary_cache_state(self):
        cache = getattr(self, "_compat_summary_cache", None)
        lock = getattr(self, "_compat_summary_cache_lock", None)
        if cache is None or lock is None:
            cache = {}
            lock = RLock()
            self._compat_summary_cache = cache
            self._compat_summary_cache_lock = lock
        return cache, lock

    def _compat_summary_cache_ttl_seconds(self) -> int:
        return max(1, int(getattr(self.settings, "public_read_cache_ttl_seconds", 30) or 30))

    def _compat_summary_cache_get(self, key: tuple[Any, ...]) -> Any | None:
        cache, lock = self._compat_summary_cache_state()
        now = monotonic()
        with lock:
            entry = cache.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                cache.pop(key, None)
                return None
            return self._compat_summary_cache_clone(value)

    def _compat_summary_cache_set(self, key: tuple[Any, ...], value: Any) -> Any:
        cache, lock = self._compat_summary_cache_state()
        with lock:
            cache[key] = (
                monotonic() + self._compat_summary_cache_ttl_seconds(),
                self._compat_summary_cache_clone(value),
            )
        return value

    def _compat_summary_cache_clone(self, value: Any) -> Any:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list):
            return list(value)
        return value

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
        file_key_sql = self._compat_file_key_sql(session)
        row = session.execute(
            text(
                f"""
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
                    {file_key_sql},
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

    def _compat_get_preview(self, session: Session, material_id: int, user_id: int | None, can_manage_all: bool) -> dict[str, Any]:
        file_key_sql = self._compat_file_key_sql(session)
        row = session.execute(
            text(
                f"""
                SELECT
                    m.id,
                    m.uploader_id,
                    m.title,
                    m.file_type,
                    {file_key_sql},
                    m.preview_source,
                    m.preview_manifest,
                    m.custom_preview_images,
                    m.status
                FROM materials m
                WHERE m.id = :material_id
                LIMIT 1
                """
            ),
            {"material_id": material_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

        is_owner = user_id is not None and int(row["uploader_id"] or 0) == int(user_id)
        if not (can_manage_all or is_owner) and self._compat_is_hidden_material(row["status"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

        preview_source = str(row["preview_source"] or "AUTO").upper()
        custom_preview_keys = self._compat_json_loads(row["custom_preview_images"])
        if preview_source == "MANUAL":
            if custom_preview_keys:
                urls = self._compat_build_custom_preview_urls(material_id, custom_preview_keys)
                return {
                    "status": "done",
                    "pageCount": len(urls),
                    "previewPages": len(urls),
                    "message": None,
                    "images": [
                        {
                            "index": index + 1,
                            "width": None,
                            "height": None,
                            "img": {"src": url, "srcSet": None, "sizes": None},
                            "webp": None,
                            "avif": None,
                            "lqip": None,
                        }
                        for index, url in enumerate(urls)
                    ],
                }
            return {"status": "failed", "pageCount": None, "previewPages": None, "message": "预览资源缺失", "images": []}

        if str(row["file_type"] or "").lower() == "pdf" and self._compat_has_text(row["file_key"]):
            manifest = self._compat_preview_manifest_payload(row["preview_manifest"])
            page_count = self._compat_preview_page_count(manifest)
            preview_pages = self._compat_preview_pages(manifest, page_count)
            pages = manifest.get("pages")
            manifest_pages = pages if isinstance(pages, list) else []
            return {
                "status": "done",
                "pageCount": page_count,
                "previewPages": preview_pages,
                "message": None,
                "images": self._compat_preview_images_from_manifest(material_id, manifest_pages, preview_pages),
            }

        return {"status": "unsupported", "pageCount": None, "previewPages": None, "message": "当前资料暂不支持预览。", "images": []}

    def _compat_generate_download(self, session: Session, material_id: int, *, user_id: int, role_mask: int | None) -> dict[str, Any]:
        row = self._compat_load_download_material_row(session, material_id)
        self._compat_assert_download_access(session, row, user_id, role_mask)
        if self._compat_should_consume_download_quota(row, user_id, role_mask):
            self._compat_consume_download_quota(session, user_id, 1)
        self._compat_register_download(session, material_id, user_id)
        session.commit()
        self.invalidate_material_summary_cache()
        return self._compat_download_payload(row)

    def _compat_generate_batch_downloads(
        self,
        session: Session,
        material_ids: list[int],
        *,
        user_id: int,
        role_mask: int | None,
    ) -> list[dict[str, Any]]:
        if not material_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择需要下载的资料")
        unique_ids = list(dict.fromkeys(material_ids))
        rows = [self._compat_load_download_material_row(session, material_id) for material_id in unique_ids]
        for row in rows:
            self._compat_assert_download_access(session, row, user_id, role_mask)
        quota_needed = sum(1 for row in rows if self._compat_should_consume_download_quota(row, user_id, role_mask))
        if quota_needed:
            self._compat_consume_download_quota(session, user_id, quota_needed)
        for row in rows:
            self._compat_register_download(session, int(row["id"]), user_id)
        session.commit()
        self.invalidate_material_summary_cache()
        return [self._compat_batch_download_payload(row) for row in rows]

    def _compat_load_download_material_row(self, session: Session, material_id: int) -> dict[str, Any]:
        file_key_sql = self._compat_file_key_sql(session, table_alias=None)
        row = session.execute(
            text(
                f"""
                SELECT
                    id,
                    uploader_id,
                    title,
                    original_filename,
                    file_type,
                    file_size,
                    {file_key_sql},
                    is_free,
                    netdisk_url,
                    netdisk_password,
                    netdisk_expired_at,
                    status
                FROM materials
                WHERE id = :material_id
                LIMIT 1
                """
            ),
            {"material_id": material_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        return dict(row)

    def _compat_assert_download_access(self, session: Session, row: dict[str, Any], user_id: int, role_mask: int | None) -> None:
        is_owner_or_admin = self._compat_is_owner_or_admin(row, user_id, role_mask)
        if self._compat_is_hidden_material(row["status"]) and not is_owner_or_admin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        if is_owner_or_admin:
            return
        if not self._compat_to_bool(row["is_free"]) and not self._compat_has_paid_access(session, int(row["id"]), user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请先购买后再下载")

    def _compat_is_owner_or_admin(self, row: dict[str, Any], user_id: int, role_mask: int | None) -> bool:
        return self._compat_as_int(row["uploader_id"], default=0) == int(user_id) or self._is_privileged(role_mask)

    def _compat_should_consume_download_quota(self, row: dict[str, Any], user_id: int, role_mask: int | None) -> bool:
        if self._is_privileged(role_mask):
            return False
        return self._compat_as_int(row["uploader_id"], default=0) != int(user_id)

    def _compat_consume_download_quota(self, session: Session, user_id: int, count: int) -> None:
        row = session.execute(
            text(
                """
                SELECT id, role_mask, free_download_quota
                FROM users
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        if self._is_privileged(self._compat_as_int(row["role_mask"], default=0)):
            return
        current_quota = self._compat_as_int(row["free_download_quota"], default=200)
        if current_quota < count:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="DOWNLOAD_QUOTA_EXHAUSTED")
        session.execute(
            text(
                """
                UPDATE users
                SET free_download_quota = :next_quota, updated_at = CURRENT_TIMESTAMP
                WHERE id = :user_id
                """
            ),
            {"next_quota": current_quota - count, "user_id": user_id},
        )

    def _compat_register_download(self, session: Session, material_id: int, user_id: int) -> None:
        existing = session.execute(
            text(
                """
                SELECT 1
                FROM material_downloads
                WHERE material_id = :material_id AND user_id = :user_id
                LIMIT 1
                """
            ),
            {"material_id": material_id, "user_id": user_id},
        ).first()
        if existing is not None:
            return
        session.execute(
            text(
                """
                INSERT INTO material_downloads (material_id, user_id, created_at)
                VALUES (:material_id, :user_id, CURRENT_TIMESTAMP)
                """
            ),
            {"material_id": material_id, "user_id": user_id},
        )
        session.execute(
            text(
                """
                UPDATE materials
                SET download_count = COALESCE(download_count, 0) + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :material_id
                """
            ),
            {"material_id": material_id},
        )

    def _compat_download_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        material_id = int(row["id"])
        file_key = self._compat_normalize_text(row["file_key"])
        if file_key:
            url, expires_at = self.asset_store.build_download_url(
                material_id=material_id,
                key=file_key,
                filename=row["original_filename"],
            )
            return {"url": url, "expiresAt": expires_at}
        if self._compat_has_text(row["netdisk_url"]):
            expires_at = row["netdisk_expired_at"].isoformat() if row["netdisk_expired_at"] is not None else None
            return {"url": row["netdisk_url"], "expiresAt": expires_at}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")

    def _compat_batch_download_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        material_id = int(row["id"])
        file_key = self._compat_normalize_text(row["file_key"])
        if file_key:
            url, expires_at = self.asset_store.build_download_url(
                material_id=material_id,
                key=file_key,
                filename=row["original_filename"],
            )
            return {
                "materialId": material_id,
                "deliveryType": "FILE",
                "url": url,
                "expiresAt": expires_at,
                "originalFilename": row["original_filename"],
                "fileType": row["file_type"],
                "fileSize": row["file_size"],
                "netdiskUrl": None,
                "netdiskPassword": None,
                "netdiskExpiredAt": None,
            }
        return {
            "materialId": material_id,
            "deliveryType": "NETDISK",
            "url": None,
            "expiresAt": None,
            "originalFilename": row["original_filename"],
            "fileType": row["file_type"],
            "fileSize": row["file_size"],
            "netdiskUrl": row["netdisk_url"],
            "netdiskPassword": row["netdisk_password"],
            "netdiskExpiredAt": row["netdisk_expired_at"].isoformat() if row["netdisk_expired_at"] else None,
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
        order_sql, order_params, recommendation_score_sql = self._compat_material_order_clause(sort=sort, profile=profile, keyword=keyword)
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
        file_key_sql = self._compat_file_key_sql(session)

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
                {file_key_sql},
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

    def _compat_material_order_clause(self, *, sort: str | None, profile: dict[str, Any] | None, keyword: str | None = None) -> tuple[str, dict[str, Any], str]:
        return compat_material_order_clause(sort=sort, profile=profile, keyword=keyword)

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
        cache_key = ("material_stats",)
        cached = self._compat_summary_cache_get(cache_key)
        if cached is not None:
            return cached
        material_stats = session.execute(
            text(
                """
                SELECT
                  COUNT(*) AS total_materials,
                  COALESCE(SUM(CASE WHEN is_free = 1 THEN 1 ELSE 0 END), 0) AS free_materials,
                  COALESCE(SUM(download_count), 0) AS total_downloads
                FROM materials
                """
            )
        ).mappings().first()
        user_count = int(session.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)
        return self._compat_summary_cache_set(
            cache_key,
            {
                "totalMaterials": int(material_stats["total_materials"] if material_stats is not None else 0),
                "freeMaterials": int(material_stats["free_materials"] if material_stats is not None else 0),
                "totalDownloads": int(material_stats["total_downloads"] if material_stats is not None else 0),
                "userCount": user_count,
            },
        )

    async def _compat_load_material_stats_async(self, session) -> dict[str, int]:
        cache_key = ("material_stats",)
        cached = self._compat_summary_cache_get(cache_key)
        if cached is not None:
            return cached
        material_result = await session.execute(
            text(
                """
                SELECT
                  COUNT(*) AS total_materials,
                  COALESCE(SUM(CASE WHEN is_free = 1 THEN 1 ELSE 0 END), 0) AS free_materials,
                  COALESCE(SUM(download_count), 0) AS total_downloads
                FROM materials
                """
            )
        )
        material_stats = material_result.mappings().first()
        users_result = await session.execute(text("SELECT COUNT(*) FROM users"))
        return self._compat_summary_cache_set(
            cache_key,
            {
                "totalMaterials": int(material_stats["total_materials"] if material_stats is not None else 0),
                "freeMaterials": int(material_stats["free_materials"] if material_stats is not None else 0),
                "totalDownloads": int(material_stats["total_downloads"] if material_stats is not None else 0),
                "userCount": int(users_result.scalar() or 0),
            },
        )

    def _compat_load_available_tags(self, session: Session, limit: int = 30) -> list[str]:
        cache_key = ("available_tags", int(limit))
        cached = self._compat_summary_cache_get(cache_key)
        if cached is not None:
            return cached
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
        return self._compat_summary_cache_set(
            cache_key,
            [str(row["tag"]) for row in rows if self._compat_has_text(row["tag"])],
        )

    async def _compat_load_available_tags_async(self, session, limit: int = 30) -> list[str]:
        cache_key = ("available_tags", int(limit))
        cached = self._compat_summary_cache_get(cache_key)
        if cached is not None:
            return cached
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
        return self._compat_summary_cache_set(
            cache_key,
            [str(row["tag"]) for row in rows if self._compat_has_text(row["tag"])],
        )

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
        order_paid_result = await session.execute(
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
        if order_paid_result.first() is not None:
            return True
        payment_paid_result = await session.execute(
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
        order_sql, order_params, recommendation_score_sql = self._compat_material_order_clause(sort=sort, profile=profile, keyword=keyword)
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
        file_key_sql = self._compat_file_key_sql(session)
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
                        m.keywords,
                        m.rating_avg,
                        m.rating_count,
                        m.like_count,
                        m.view_count,
                        m.download_count,
                        m.sales_count,
                        m.created_at,
                        {file_key_sql},
                        m.netdisk_url,
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
        file_key_sql = self._compat_file_key_sql(session)
        row = (
            await session.execute(
                text(
                    f"""
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
                        {file_key_sql},
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

    def _compat_preview_manifest_payload(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _compat_preview_page_count(self, manifest: dict[str, Any]) -> int:
        explicit_count = self._compat_as_int(manifest.get("pageCount"), default=0)
        if explicit_count > 0:
            return explicit_count
        pages = manifest.get("pages")
        if isinstance(pages, list) and pages:
            return len(pages)
        return int(getattr(self.settings, "material_preview_pages_large", 5) or 5)

    def _compat_preview_pages(self, manifest: dict[str, Any], page_count: int) -> int:
        explicit_pages = self._compat_as_int(manifest.get("previewPages"), default=0)
        if explicit_pages > 0:
            return min(explicit_pages, max(1, page_count))
        pages = manifest.get("pages")
        if isinstance(pages, list) and pages:
            return min(len(pages), max(1, page_count))
        configured_pages = int(getattr(self.settings, "material_preview_pages_small", 3) or 3)
        return min(max(1, configured_pages), max(1, page_count))

    def _compat_preview_images_from_manifest(self, material_id: int, pages: list[Any], preview_pages: int) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        for position in range(preview_pages):
            page = pages[position] if position < len(pages) and isinstance(pages[position], dict) else {}
            index = self._compat_as_int(page.get("index"), default=position + 1) if page else position + 1
            if index <= 0:
                index = position + 1
            key = self._compat_normalize_text(page.get("key")) if page else None
            image = self._preview_image_payload(material_id, index, key=key, placeholder=not bool(key))
            width = self._compat_as_int(page.get("width"), default=0) if page else 0
            height = self._compat_as_int(page.get("height"), default=0) if page else 0
            if width > 0:
                image["width"] = width
            if height > 0:
                image["height"] = height
            images.append(image)
        return images

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
