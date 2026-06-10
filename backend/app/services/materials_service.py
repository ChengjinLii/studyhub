from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.async_db import async_session_scope
from app.core.config import Settings
from app.core.profile_metadata import DEFAULT_FREE_DOWNLOAD_QUOTA
from app.core.upload_validation import validate_file_size, validate_image_upload
from app.integrations.material_asset_store import MaterialAssetStore
from app.models.auth import AuthUser
from app.models.materials import MaterialFavoriteRecord, MaterialRatingRecord, MaterialRecord
from app.repos.auth_repo import AuthRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.admin import AdminMaterialBatchUpdatePayload
from app.schemas.materials import MaterialCreatePayload, MaterialUpdatePayload, ReviewPayload
from app.services.materials_query_support import (
    compat_extract_primary_major,
    compat_major_matches,
    compat_material_filter_parts,
    compat_material_order_clause,
    compat_normalize_major_selections,
    compat_recommendation_score,
    compat_sort_material_rows,
)
from app.services.materials_compat import MaterialsCompatMixin
from app.services.materials_serializers import admin_material_item, load_json_list, material_has_file, material_list_item
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
    count_users_with_seed_fallback,
    parse_iso_datetime,
    serialize_datetime,
    serialize_user_snapshot,
)


ROLE_ADMIN = 8
ROLE_DEVELOPER = 16
VISIBLE_STATUSES = {"VISIBLE", "visible", "", None}
VISIBLE_MATERIAL_STATUS_SQL = "(m.status IS NULL OR LOWER(m.status) NOT IN ('hidden', 'removed'))"


class MaterialsService(MaterialsCompatMixin):
    def __init__(
        self,
        settings: Settings,
        read_repo: ReadApiRepository,
        auth_repo: AuthRepository,
        material_repo: MaterialRepository,
        asset_store: MaterialAssetStore,
    ) -> None:
        self.settings = settings
        self.read_repo = read_repo
        self.auth_repo = auth_repo
        self.material_repo = material_repo
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
        if self.settings.requires_private_env_file:
            return self._compat_list_materials(
                session,
                current_user_id,
                keyword=keyword,
                school=school,
                college=college,
                major=major,
                tag=tag,
                grade_value=grade_value,
                course_category=course_category,
                price=price,
                sort=sort,
                page=page,
                size=size,
            )
        self._bootstrap(session)
        current_user = self._resolve_current_user(session, current_user_id)
        visible_materials = self.material_repo.list_visible_materials(session)
        items = [material for material in visible_materials if self._matches_material(material, keyword, school, college, major, tag, grade_value, course_category, price)]

        if (sort or "").lower() == "price":
            items.sort(key=lambda material: (material.price, -self._material_created_ts(material)))
        else:
            items.sort(
                key=lambda material: (
                    -self._recommendation_score(material, current_user),
                    -int(material.download_count or 0),
                    -self._material_created_ts(material),
                )
            )

        safe_page = max(page, 1)
        safe_size = max(1, min(size, 100))
        start = (safe_page - 1) * safe_size
        end = start + safe_size
        page_items = [material_list_item(material) for material in items[start:end]]
        available_tags = sorted({tag_name for material in visible_materials for tag_name in self._loads(material.tags_json)})
        return {
            "items": page_items,
            "meta": {"page": safe_page, "size": safe_size, "total": len(items)},
            "stats": {
                "totalMaterials": len(items),
                "freeMaterials": sum(1 for material in visible_materials if material.is_free),
                "totalDownloads": sum(int(material.download_count or 0) for material in visible_materials),
                "userCount": self._user_count_with_seed_fallback(session),
            },
            "availableTags": available_tags,
        }

    async def list_materials_async(
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
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(
                self.list_materials,
                session,
                current_user_id,
                keyword=keyword,
                school=school,
                college=college,
                major=major,
                tag=tag,
                grade_value=grade_value,
                course_category=course_category,
                price=price,
                sort=sort,
                page=page,
                size=size,
            )

        safe_page = max(page, 1)
        safe_size = max(1, min(size, 100))
        start = (safe_page - 1) * safe_size
        count_call = self._call_with_new_async_session(
            self._compat_count_material_rows_async,
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=grade_value,
            course_category=course_category,
            price=price,
        )
        stats_call = self._call_with_new_async_session(self._compat_load_material_stats_async)
        tags_call = self._call_with_new_async_session(self._compat_load_available_tags_async)
        if current_user_id is None:
            profile = None
            total, stats, available_tags, page_rows = await asyncio.gather(
                count_call,
                stats_call,
                tags_call,
                self._call_with_new_async_session(
                    self._compat_load_material_rows_async,
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
                ),
            )
        else:
            profile, total, stats, available_tags = await asyncio.gather(
                self._call_with_new_async_session(self._compat_load_user_profile_async, current_user_id),
                count_call,
                stats_call,
                tags_call,
            )
            page_rows = await self._call_with_new_async_session(
                self._compat_load_material_rows_async,
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
        tags_by_material, comment_counts = await asyncio.gather(
            self._call_with_new_async_session(self._compat_load_tags_map_async, material_ids),
            self._call_with_new_async_session(self._compat_load_comment_counts_async, material_ids),
        )
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
            "stats": stats,
            "availableTags": available_tags,
        }

    def get_recommendations(self, session: Session, current_user_id: int | None, limit: int | None) -> list[dict[str, Any]]:
        if self.settings.requires_private_env_file:
            return self._compat_get_recommendations(session, current_user_id, limit)
        self._bootstrap(session)
        current_user = self._resolve_current_user(session, current_user_id)
        items = self.material_repo.list_visible_materials(session)
        items.sort(
            key=lambda material: (
                -self._recommendation_score(material, current_user),
                -int(material.download_count or 0),
                -self._material_created_ts(material),
            )
        )
        safe_limit = clamp_limit(limit, max_value=100)
        sliced = items[:safe_limit] if safe_limit else items
        return [material_list_item(material) for material in sliced]

    async def get_recommendations_async(
        self,
        session: Session,
        current_user_id: int | None,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(self.get_recommendations, session, current_user_id, limit)

        profile = (
            None
            if current_user_id is None
            else await self._call_with_new_async_session(self._compat_load_user_profile_async, current_user_id)
        )
        safe_limit = clamp_limit(limit, max_value=100)
        rows = await self._call_with_new_async_session(
            self._compat_load_material_rows_async,
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
        material_ids = [int(row["id"]) for row in rows]
        tags_by_material, comment_counts = await asyncio.gather(
            self._call_with_new_async_session(self._compat_load_tags_map_async, material_ids),
            self._call_with_new_async_session(self._compat_load_comment_counts_async, material_ids),
        )
        return [
            self._compat_to_list_item(
                row,
                tags=tags_by_material.get(int(row["id"]), []),
                comment_count=comment_counts.get(int(row["id"]), 0),
            )
            for row in rows
        ]

    def _user_count_with_seed_fallback(self, session: Session) -> int:
        return count_users_with_seed_fallback(session, self.auth_repo, self.read_repo)

    async def _call_with_new_async_session(self, loader, *args, **kwargs):
        async with async_session_scope() as session:
            return await loader(session, *args, **kwargs)

    def get_detail(self, session: Session, current_user_id: int | None, material_id: int, can_manage_all: bool = False) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_get_detail(session, current_user_id, material_id, can_manage_all)
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, current_user_id, can_manage_all)
        purchased = self._has_paid_access(session, material, current_user_id, can_manage_all) or material.is_free
        liked = current_user_id is not None and self.material_repo.find_like(session, material_id, current_user_id) is not None
        favorited = current_user_id is not None and self.material_repo.find_favorite(session, material_id, current_user_id) is not None
        rating_record = self.material_repo.find_rating(session, material_id, current_user_id) if current_user_id is not None else None
        detail = material_list_item(material)
        detail.update(
            {
                "originalFilename": material.original_filename,
                "fileType": material.file_type.upper() if material.file_type else None,
                "fileSize": material.file_size,
                "previewManifest": material.preview_manifest,
                "customPreviewText": material.custom_preview_text,
                "customPreviewImages": self._public_custom_preview_urls(material_id, material),
                "netdiskUrl": material.netdisk_url,
                "netdiskPassword": material.netdisk_password,
                "netdiskExpiredAt": material.netdisk_expired_at.isoformat() if material.netdisk_expired_at else None,
                "netdiskReminderAt": material.netdisk_reminder_at.isoformat() if material.netdisk_reminder_at else None,
                "netdiskAccessible": bool(material.netdisk_url),
                "purchased": purchased or (current_user_id is not None and material.uploader_id == current_user_id) or can_manage_all,
                "favorited": favorited,
                "liked": liked,
                "myRating": rating_record.rating if rating_record is not None else None,
                "hasFile": self._has_file(material),
                "versions": [
                    {
                        "id": version.id,
                        "versionLabel": version.version_label,
                        "createdAt": self._serialize_datetime(version.created_at),
                    }
                    for version in self.material_repo.list_versions(session, material_id)
                ],
                "reviews": [
                    {
                        "id": review.id,
                        "reviewer": review.reviewer,
                        "rating": review.rating,
                        "comment": review.comment,
                        "createdAt": self._serialize_datetime(review.created_at),
                    }
                    for review in self.material_repo.list_reviews(session, material_id)
                ],
            }
        )
        return detail

    async def get_detail_async(
        self,
        session: Session,
        current_user_id: int | None,
        material_id: int,
        can_manage_all: bool = False,
    ) -> dict[str, Any]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(self.get_detail, session, current_user_id, material_id, can_manage_all)

        row = await self._call_with_new_async_session(self._compat_load_material_detail_row_async, material_id)
        is_owner = current_user_id is not None and int(row["uploader_id"] or 0) == current_user_id
        if not (can_manage_all or is_owner) and self._compat_is_hidden_material(row["status"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        detail_base = {
            "id": int(row["id"]),
            "uploaderId": self._compat_as_int(row["uploader_id"]),
            "uploaderUsername": row["uploader_username"],
            "uploaderNickname": row["uploader_nickname"],
            "copyrightOwner": self._compat_normalize_text(row["keywords"]),
            "title": row["title"] or "",
            "description": row["description"] or "",
            "originalFilename": row["original_filename"],
            "fileType": row["file_type"],
            "hasFile": self._compat_has_text(row["file_key"]),
            "fileSize": self._compat_as_int(row["file_size"], default=0),
            "price": self._compat_cents_to_price(row["price"]),
            "free": self._compat_to_bool(row["is_free"]),
            "school": row["school"],
            "college": row["college"],
            "major": row["major"],
            "generalEducation": self._compat_to_bool(row["is_general_education"]),
            "hasNetdisk": self._compat_has_text(row["netdisk_url"]),
            "courseCategory": row["course_category"] or "MAJOR",
            "gradeType": row["grade_type"] or "UG",
            "gradeValue": row["grade_value"] or "",
            "previewWatermarkEnabled": self._compat_to_bool(row["preview_watermark_enabled"], default=True),
            "previewSource": row["preview_source"] or "AUTO",
            "previewManifest": self._compat_serialize_preview_manifest(row["preview_manifest"]),
            "customPreviewText": row["custom_preview_text"] if current_user_id is not None else None,
            "ratingAvg": self._compat_as_float(row["rating_avg"]),
            "ratingCount": self._compat_as_int(row["rating_count"]),
            "likeCount": self._compat_as_int(row["like_count"]),
            "viewCount": self._compat_as_int(row["view_count"]),
            "downloadCount": self._compat_as_int(row["download_count"]),
            "salesCount": self._compat_as_int(row["sales_count"]),
        }
        favorited = False
        liked = False
        my_rating = None
        purchased = False
        auxiliary_calls = [
            self._call_with_new_async_session(self._compat_load_tags_map_async, [material_id]),
            self._call_with_new_async_session(self._compat_load_comment_counts_async, [material_id]),
            self._call_with_new_async_session(self._compat_load_versions_async, material_id),
            self._call_with_new_async_session(self._compat_load_reviews_async, material_id),
        ]
        if current_user_id is not None:
            auxiliary_calls.extend(
                [
                    self._call_with_new_async_session(
                        self._compat_material_relation_exists_async,
                        """
                        SELECT 1
                        FROM favorites
                        WHERE material_id = :material_id AND user_id = :user_id
                        LIMIT 1
                        """,
                        material_id,
                        current_user_id,
                    ),
                    self._call_with_new_async_session(
                        self._compat_material_relation_exists_async,
                        """
                        SELECT 1
                        FROM material_likes
                        WHERE material_id = :material_id AND user_id = :user_id
                        LIMIT 1
                        """,
                        material_id,
                        current_user_id,
                    ),
                    self._call_with_new_async_session(self._compat_load_my_rating_async, material_id, current_user_id),
                    self._call_with_new_async_session(self._compat_has_paid_access_async, material_id, current_user_id),
                    self._compat_build_custom_preview_urls_async(
                        material_id,
                        self._compat_json_loads(row["custom_preview_images"]),
                    ),
                ]
            )
        auxiliary_results = await asyncio.gather(*auxiliary_calls)
        tags_map, comment_counts, versions, reviews = auxiliary_results[:4]
        custom_preview_images = []
        if current_user_id is not None:
            favorited = bool(auxiliary_results[4])
            liked = bool(auxiliary_results[5])
            my_rating = auxiliary_results[6]
            purchased = bool(auxiliary_results[7])
            custom_preview_images = auxiliary_results[8]
        netdisk_accessible = detail_base["hasNetdisk"] and (detail_base["free"] or purchased or can_manage_all or is_owner)
        detail_base.update(
            {
                "tags": tags_map.get(material_id, []),
                "commentCount": comment_counts.get(material_id, 0),
                "netdiskUrl": row["netdisk_url"] if netdisk_accessible else None,
                "netdiskPassword": row["netdisk_password"] if netdisk_accessible else None,
                "netdiskExpiredAt": row["netdisk_expired_at"].isoformat() if row["netdisk_expired_at"] is not None else None,
                "netdiskReminderAt": row["netdisk_reminder_at"].isoformat() if row["netdisk_reminder_at"] is not None else None,
                "netdiskAccessible": netdisk_accessible,
                "customPreviewImages": custom_preview_images,
                "favorited": favorited,
                "purchased": purchased,
                "liked": liked,
                "myRating": my_rating,
                "versions": versions,
                "reviews": reviews,
            }
        )
        return detail_base

    def record_view(
        self,
        session: Session,
        material_id: int,
        user_id: int | None,
        can_manage_all: bool,
        viewer_token: str | None,
    ) -> int:
        if self.settings.requires_private_env_file:
            return self._compat_record_view(session, material_id, user_id, can_manage_all, viewer_token)
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, user_id, can_manage_all)
        current_view_count = int(material.view_count or 0)
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
        material.view_count = next_view_count
        self.material_repo.save_material(session, material)
        session.commit()
        return next_view_count

    def get_preview(self, session: Session, material_id: int, user_id: int, can_manage_all: bool) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_get_preview(session, material_id, user_id, can_manage_all)
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, user_id, can_manage_all)
        if material.preview_source == "MANUAL":
            manual_keys = self._loads(material.manual_preview_keys_json)
            custom_images = self._loads(material.custom_preview_images_json)
            if manual_keys:
                return {
                    "status": "done",
                    "pageCount": len(manual_keys),
                    "previewPages": len(manual_keys),
                    "message": None,
                    "images": [
                        self._preview_image_payload(material_id, index + 1, key=key, placeholder=False)
                        for index, key in enumerate(manual_keys)
                    ],
                }
            if custom_images:
                return {
                    "status": "done",
                    "pageCount": len(custom_images),
                    "previewPages": len(custom_images),
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
                        for index, url in enumerate(self._public_custom_preview_urls(material_id, material))
                    ],
                }
            return {"status": "failed", "pageCount": None, "previewPages": None, "message": "预览资源缺失", "images": []}

        if (material.file_type or "").lower() == "pdf" and self._has_file(material):
            page_count = int(material.preview_page_count or self.settings.material_preview_pages_large)
            preview_pages = int(material.preview_pages or min(page_count, self.settings.material_preview_pages_small))
            return {
                "status": "done",
                "pageCount": page_count,
                "previewPages": preview_pages,
                "message": None,
                "images": [
                    self._preview_image_payload(material_id, index + 1, key=None, placeholder=True)
                    for index in range(preview_pages)
                ],
            }

        return {"status": "unsupported", "pageCount": None, "previewPages": None, "message": "当前资料暂不支持预览。", "images": []}

    def create_material(
        self,
        session: Session,
        payload: MaterialCreatePayload,
        *,
        uploader_id: int,
        zip_file: UploadFile | None,
        markdown_file: UploadFile | None,
        previews: list[UploadFile],
        custom_previews: list[UploadFile],
    ) -> dict[str, Any]:
        seed = self._bootstrap(session)
        uploader = self._require_user(session, uploader_id)
        material_id = self.material_repo.next_material_id(session, seed)
        file_upload = zip_file or markdown_file
        if (payload.deliveryMethod or "FILE").upper() == "FILE" and file_upload is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")

        material = MaterialRecord(
            id=material_id,
            source="local",
            uploader_id=uploader.id,
            uploader_username=uploader.username,
            uploader_nickname=uploader.nickname or uploader.username,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._apply_payload_to_material(session, material, payload, file_upload=file_upload, previews=previews, custom_previews=custom_previews, is_create=True)
        self.material_repo.save_material(session, material)
        self.material_repo.add_version(session, material_id=material.id, version_label="v1.0")
        session.commit()
        self.invalidate_material_summary_cache()
        return self.get_detail(session, uploader_id, material.id)

    def update_material(
        self,
        session: Session,
        material_id: int,
        payload: MaterialUpdatePayload,
        *,
        operator_id: int,
        can_manage_all: bool,
        zip_file: UploadFile | None,
        markdown_file: UploadFile | None,
        previews: list[UploadFile],
        custom_previews: list[UploadFile],
    ) -> dict[str, Any]:
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, operator_id, can_manage_all, require_owner=True)
        file_upload = zip_file or markdown_file
        self._apply_payload_to_material(session, material, payload, file_upload=file_upload, previews=previews, custom_previews=custom_previews, is_create=False)
        version_index = len(self.material_repo.list_versions(session, material.id)) + 1
        self.material_repo.add_version(session, material_id=material.id, version_label=f"v{version_index}.0")
        self.material_repo.save_material(session, material)
        session.commit()
        self.invalidate_material_summary_cache()
        return self.get_detail(session, operator_id, material.id, can_manage_all)

    def delete_material(self, session: Session, material_id: int, *, operator_id: int, can_manage_all: bool) -> None:
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, operator_id, can_manage_all, require_owner=True)
        material.status = "REMOVED"
        material.deleted_at = datetime.now(UTC)
        self.material_repo.save_material(session, material)
        session.commit()
        self.invalidate_material_summary_cache()

    def restore_material(self, session: Session, material_id: int, *, can_manage_all: bool) -> dict[str, Any]:
        self._bootstrap(session)
        if not can_manage_all:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权恢复该资料")
        material = self._ensure_material_exists(session, material_id)
        material.status = "VISIBLE"
        material.deleted_at = None
        self.material_repo.save_material(session, material)
        session.commit()
        self.invalidate_material_summary_cache()
        return admin_material_item(material)

    def list_for_admin(
        self,
        session: Session,
        *,
        page: int,
        size: int,
        status_value: str | None,
    ) -> dict[str, Any]:
        if getattr(self.settings, "requires_private_env_file", False):
            return self._compat_list_for_admin(session, page=page, size=size, status_value=status_value)
        self._bootstrap(session)
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        total = self.material_repo.count_materials_for_admin(session, status_value=status_value)
        items = self.material_repo.list_materials_for_admin(
            session,
            status_value=status_value,
            limit=safe_size,
            offset=safe_page * safe_size,
        )
        return {
            "items": [admin_material_item(item) for item in items],
            "meta": {"page": safe_page, "size": safe_size, "total": total},
        }

    def _compat_list_for_admin(
        self,
        session: Session,
        *,
        page: int,
        size: int,
        status_value: str | None,
    ) -> dict[str, Any]:
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        offset = safe_page * safe_size
        normalized_status = (status_value or "").strip().lower()
        params: dict[str, Any] = {"limit": safe_size, "offset": offset}
        if normalized_status:
            where_sql = "LOWER(TRIM(COALESCE(m.status, ''))) = :status"
            params["status"] = normalized_status
        else:
            where_sql = "LOWER(TRIM(COALESCE(m.status, ''))) != 'removed'"

        total = int(session.execute(text(f"SELECT COUNT(*) FROM materials m WHERE {where_sql}"), params).scalar() or 0)
        order_sql = "m.deleted_at DESC, m.created_at DESC, m.id DESC" if normalized_status == "removed" else "m.created_at DESC, m.id DESC"
        rows = session.execute(
            text(
                f"""
                SELECT
                    m.id,
                    m.title,
                    m.school,
                    m.college,
                    m.major,
                    m.grade_value,
                    m.grade_type,
                    m.course_category,
                    m.price,
                    m.is_free,
                    m.status,
                    m.review_status,
                    m.uploader_id,
                    u.username AS uploader_username,
                    u.nickname AS uploader_nickname,
                    m.download_count,
                    m.sales_count,
                    m.created_at,
                    m.updated_at,
                    m.deleted_at
                FROM materials m
                LEFT JOIN users u ON u.id = m.uploader_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        material_ids = [int(row["id"]) for row in rows]
        tags_map = self._compat_load_tags_map(session, material_ids)
        return {
            "items": [self._compat_admin_material_item(dict(row), tags_map.get(int(row["id"]), [])) for row in rows],
            "meta": {"page": safe_page, "size": safe_size, "total": total},
        }

    def _compat_admin_material_item(self, row: dict[str, Any], tags: list[str]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "title": row["title"],
            "school": row["school"],
            "college": row["college"],
            "major": row["major"],
            "gradeValue": row["grade_value"],
            "gradeType": row["grade_type"],
            "courseCategory": row["course_category"],
            "tags": tags,
            "price": self._compat_cents_to_price(row["price"]),
            "free": self._compat_to_bool(row["is_free"]),
            "status": row["status"],
            "reviewStatus": row["review_status"],
            "uploaderId": self._compat_as_int(row["uploader_id"]),
            "uploaderUsername": row["uploader_username"],
            "uploaderNickname": row["uploader_nickname"],
            "downloadCount": self._compat_as_int(row["download_count"]),
            "salesCount": self._compat_as_int(row["sales_count"]),
            "createdAt": self._compat_serialize_datetime(row["created_at"]),
            "updatedAt": self._compat_serialize_datetime(row["updated_at"]),
            "deletedAt": self._compat_serialize_datetime(row["deleted_at"]),
        }

    def batch_update_materials(self, session: Session, payload: AdminMaterialBatchUpdatePayload) -> dict[str, Any]:
        self._bootstrap(session)
        if not payload.materialIds:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先选择至少一条资料")
        has_updates = any(
            value not in (None, "")
            for value in [payload.college, payload.major, payload.gradeValue, payload.courseCategory, payload.tags]
        )
        if not has_updates:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少填写一个需要更新的字段")
        updated = 0
        missing_ids: list[int] = []
        tag_mode = (payload.tagsMode or "replace").strip().lower()
        for material_id in payload.materialIds:
            material = self.material_repo.get_material(session, material_id)
            if material is None:
                missing_ids.append(material_id)
                continue
            changed = False
            if payload.college is not None and material.college != (payload.college or None):
                material.college = payload.college or None
                changed = True
            if payload.major is not None and material.major != (payload.major or None):
                material.major = payload.major or None
                changed = True
            if payload.gradeValue is not None and material.grade_value != (payload.gradeValue or None):
                material.grade_value = payload.gradeValue or None
                changed = True
            if payload.courseCategory is not None and material.course_category != (payload.courseCategory or None):
                material.course_category = payload.courseCategory or None
                changed = True
            if payload.tags is not None:
                existing_tags = self._loads(material.tags_json)
                next_tags = self._split_tags(payload.tags)
                if tag_mode == "append":
                    merged = existing_tags[:]
                    for tag in next_tags:
                        if tag not in merged:
                            merged.append(tag)
                    next_tags = merged
                if existing_tags != next_tags:
                    material.tags_json = self._json_dumps(next_tags)
                    changed = True
            if changed:
                self.material_repo.save_material(session, material)
                updated += 1
        session.commit()
        if updated:
            self.invalidate_material_summary_cache()
        return {"updated": updated, "requested": len(payload.materialIds), "missingIds": missing_ids}

    def batch_delete_materials(self, session: Session, material_ids: list[int]) -> dict[str, Any]:
        self._bootstrap(session)
        deleted = 0
        failed_ids: list[int] = []
        for material_id in material_ids:
            material = self.material_repo.get_material(session, material_id)
            if material is None:
                failed_ids.append(material_id)
                continue
            if (material.status or "").upper() != "REMOVED":
                material.status = "REMOVED"
                material.deleted_at = datetime.now(UTC)
                self.material_repo.save_material(session, material)
            deleted += 1
        session.commit()
        if deleted:
            self.invalidate_material_summary_cache()
        return {"deleted": deleted, "requested": len(material_ids), "failedIds": failed_ids}

    def batch_restore_materials(self, session: Session, material_ids: list[int]) -> dict[str, Any]:
        self._bootstrap(session)
        restored = 0
        failed_ids: list[int] = []
        for material_id in material_ids:
            material = self.material_repo.get_material(session, material_id)
            if material is None:
                failed_ids.append(material_id)
                continue
            material.status = "VISIBLE"
            material.deleted_at = None
            self.material_repo.save_material(session, material)
            restored += 1
        session.commit()
        if restored:
            self.invalidate_material_summary_cache()
        return {"restored": restored, "requested": len(material_ids), "failedIds": failed_ids}

    def add_favorite(self, session: Session, material_id: int, user_id: int) -> None:
        self._bootstrap(session)
        self._ensure_material_exists(session, material_id)
        self._require_user(session, user_id)
        if self.material_repo.find_favorite(session, material_id, user_id) is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已收藏")
        self.material_repo.add_favorite(session, material_id=material_id, user_id=user_id)
        session.commit()

    def remove_favorite(self, session: Session, material_id: int, user_id: int) -> None:
        self._bootstrap(session)
        entity = self.material_repo.find_favorite(session, material_id, user_id)
        if entity is None:
            session.commit()
            return
        self.material_repo.remove_favorite(session, entity)
        session.commit()

    def like(self, session: Session, material_id: int, user_id: int) -> int:
        self._bootstrap(session)
        material = self._ensure_material_exists(session, material_id)
        current_like_count = int(material.like_count or 0)
        if self.material_repo.find_like(session, material_id, user_id) is not None:
            return current_like_count
        self.material_repo.add_like(session, material_id=material_id, user_id=user_id)
        next_like_count = current_like_count + 1
        material.like_count = next_like_count
        self.material_repo.save_material(session, material)
        session.commit()
        return next_like_count

    def unlike(self, session: Session, material_id: int, user_id: int) -> int:
        self._bootstrap(session)
        material = self._ensure_material_exists(session, material_id)
        current_like_count = int(material.like_count or 0)
        entity = self.material_repo.find_like(session, material_id, user_id)
        if entity is None:
            return current_like_count
        self.material_repo.remove_like(session, entity)
        next_like_count = max(0, current_like_count - 1)
        material.like_count = next_like_count
        self.material_repo.save_material(session, material)
        session.commit()
        return next_like_count

    def rate_material(self, session: Session, material_id: int, user_id: int, rating: int) -> dict[str, Any]:
        self._bootstrap(session)
        material = self._ensure_material_exists(session, material_id)
        user = self._require_user(session, user_id)
        entity = self.material_repo.find_rating(session, material_id, user_id)
        count = int(material.rating_count or 0)
        avg = float(material.rating_avg or 0)
        if entity is None:
            entity = MaterialRatingRecord(material_id=material_id, user_id=user_id, rating=rating)
            self.material_repo.save_rating(session, entity)
            next_count = count + 1
            next_avg = ((avg * count) + rating) / next_count if next_count else float(rating)
        else:
            previous = int(entity.rating)
            entity.rating = rating
            self.material_repo.save_rating(session, entity)
            next_count = count
            next_avg = ((avg * count) - previous + rating) / count if count else float(rating)
        rounded_avg = round(next_avg, 2)
        reviewer_name = user.nickname
        material.rating_count = next_count
        material.rating_avg = rounded_avg
        self.material_repo.save_material(session, material)
        session.commit()
        return {"ratingAvg": rounded_avg, "ratingCount": next_count, "rating": rating, "reviewer": reviewer_name}

    def add_review(self, session: Session, material_id: int, user_id: int, payload: ReviewPayload) -> None:
        self._bootstrap(session)
        material = self._ensure_material_exists(session, material_id)
        user = self._require_user(session, user_id)
        self.material_repo.add_review(
            session,
            material_id=material_id,
            user_id=user_id,
            reviewer=user.nickname or user.username,
            rating=payload.rating,
            comment=payload.comment.strip() if payload.comment else None,
        )
        self.rate_material(session, material_id, user_id, payload.rating)
        refreshed = self.material_repo.get_material(session, material_id)
        if refreshed is not None:
            self.material_repo.save_material(session, refreshed)
        session.commit()

    def generate_download(self, session: Session, material_id: int, *, user_id: int, role_mask: int | None) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_generate_download(session, material_id, user_id=user_id, role_mask=role_mask)
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, user_id, self._is_privileged(role_mask))
        self._assert_can_download(session, material, user_id, role_mask)
        self._consume_quota_if_needed(session, material, user_id, role_mask)
        self._register_download(session, material, user_id)
        session.commit()
        self.invalidate_material_summary_cache()
        if self._has_file(material):
            url, expires_at = self.asset_store.build_download_url(material_id=material.id, key=material.file_storage_key or "", filename=material.original_filename)
            return {"url": url, "expiresAt": expires_at}
        if material.netdisk_url:
            return {"url": material.netdisk_url, "expiresAt": material.netdisk_expired_at.isoformat() if material.netdisk_expired_at else None}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")

    def generate_batch_downloads(self, session: Session, material_ids: list[int], *, user_id: int, role_mask: int | None) -> list[dict[str, Any]]:
        if self.settings.requires_private_env_file:
            return self._compat_generate_batch_downloads(session, material_ids, user_id=user_id, role_mask=role_mask)
        self._bootstrap(session)
        if not material_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择需要下载的资料")
        unique_ids = list(dict.fromkeys(material_ids))
        materials = [self._load_accessible_material(session, material_id, user_id, self._is_privileged(role_mask)) for material_id in unique_ids]
        quota_needed = sum(1 for material in materials if self._should_consume_quota(material, user_id, role_mask))
        if quota_needed:
            self._consume_download_quota(session, user_id, quota_needed)
        results: list[dict[str, Any]] = []
        for material in materials:
            self._assert_download_access_without_quota(session, material, user_id, role_mask)
            self._register_download(session, material, user_id)
            if self._has_file(material):
                url, expires_at = self.asset_store.build_download_url(material_id=material.id, key=material.file_storage_key or "", filename=material.original_filename)
                results.append(
                    {
                        "materialId": material.id,
                        "deliveryType": "FILE",
                        "url": url,
                        "expiresAt": expires_at,
                        "originalFilename": material.original_filename,
                        "fileType": material.file_type,
                        "fileSize": material.file_size,
                        "netdiskUrl": None,
                        "netdiskPassword": None,
                        "netdiskExpiredAt": None,
                    }
                )
            else:
                results.append(
                    {
                        "materialId": material.id,
                        "deliveryType": "NETDISK",
                        "url": None,
                        "expiresAt": None,
                        "originalFilename": material.original_filename,
                        "fileType": material.file_type,
                        "fileSize": material.file_size,
                        "netdiskUrl": material.netdisk_url,
                        "netdiskPassword": material.netdisk_password,
                        "netdiskExpiredAt": material.netdisk_expired_at.isoformat() if material.netdisk_expired_at else None,
                    }
                )
        session.commit()
        self.invalidate_material_summary_cache()
        return results

    def resolve_download_asset(self, session: Session, material_id: int, token: str) -> tuple[MaterialRecord, Path | None, str]:
        self._bootstrap(session)
        claims = self.asset_store.verify_download_token(material_id=material_id, token=token)
        material = self._ensure_material_exists(session, material_id)
        key = claims.get("key")
        filename = str(claims.get("filename") or material.original_filename or f"material-{material_id}.{material.file_type or 'zip'}")
        path = self.asset_store.resolve_path(str(key)) if key else None
        return material, path, filename

    def resolve_preview_asset(self, session: Session, material_id: int, index: int, token: str) -> tuple[MaterialRecord, dict[str, Any]]:
        self._bootstrap(session)
        claims = self.asset_store.verify_preview_token(material_id=material_id, token=token)
        if int(claims.get("index", 0) or 0) != index:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="链接已失效")
        material = self._ensure_material_exists(session, material_id)
        return material, claims

    def resolve_public_custom_preview_path(self, session: Session, material_id: int, index: int, token: str) -> Path:
        self._bootstrap(session)
        claims = self.asset_store.verify_custom_preview_token(material_id=material_id, token=token)
        if int(claims.get("index", 0) or 0) != index:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="链接已失效")
        material = self._ensure_material_exists(session, material_id)
        keys = self._loads(material.custom_preview_images_json)
        if index < 1 or index > len(keys):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预览图片不存在")
        key = keys[index - 1]
        if str(claims.get("key") or "") != str(key):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="链接已失效")
        if self._is_external_url(key):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预览图片不存在")
        return self.asset_store.resolve_path(key)

    def list_user_uploads(self, session: Session, target_user_id: int) -> list[MaterialRecord]:
        self._bootstrap(session)
        items = [material for material in self.material_repo.list_visible_materials(session) if int(material.uploader_id or 0) == target_user_id]
        items.sort(key=lambda item: (-(item.download_count or 0), -self._material_created_ts(item)))
        return items

    def _apply_payload_to_material(
        self,
        session: Session,
        material: MaterialRecord,
        payload: MaterialCreatePayload | MaterialUpdatePayload,
        *,
        file_upload: UploadFile | None,
        previews: list[UploadFile],
        custom_previews: list[UploadFile],
        is_create: bool,
    ) -> None:
        if file_upload is not None:
            validate_file_size(
                file_upload,
                max_size_bytes=self.settings.material_file_max_size_bytes,
                too_large_detail="资料文件不能超过 50MB",
            )
        if len(previews) > self.settings.material_manual_preview_max_images:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手动预览图最多上传 10 张")
        if len(custom_previews) > self.settings.material_custom_preview_max_images:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="自定义配图最多上传 5 张")
        for preview_file in previews:
            validate_image_upload(
                preview_file,
                settings=self.settings,
                max_size_bytes=self.settings.material_preview_image_max_size_bytes,
                missing_detail="请上传有效的预览图片",
                invalid_type_detail="预览图片仅支持 PNG、JPG、WEBP、GIF、BMP、AVIF、HEIC、HEIF 格式",
                too_large_detail="预览图片不能超过 5MB",
            )
        for preview_file in custom_previews:
            validate_image_upload(
                preview_file,
                settings=self.settings,
                max_size_bytes=self.settings.material_preview_image_max_size_bytes,
                missing_detail="请上传有效的自定义配图",
                invalid_type_detail="自定义配图仅支持 PNG、JPG、WEBP、GIF、BMP、AVIF、HEIC、HEIF 格式",
                too_large_detail="自定义配图不能超过 5MB",
            )
        delivery_method = (payload.deliveryMethod or material.delivery_method or "FILE").upper()
        material.title = payload.title.strip()
        material.description = payload.description
        material.price = int(payload.price or 0)
        material.is_free = material.price <= 0
        material.school = payload.school
        material.college = payload.college or None
        material.major = payload.major or None
        material.general_course = bool(payload.generalCourse)
        material.course_category = payload.courseCategory or ("GENERAL" if payload.generalCourse else "MAJOR")
        material.grade_type = payload.gradeType or material.grade_type or "STAGE"
        material.grade_value = payload.gradeValue or material.grade_value or "大一"
        material.keywords = payload.keywords
        material.tags_json = self._json_dumps(self._split_tags(payload.tags))
        material.delivery_method = delivery_method
        material.netdisk_url = payload.netdiskUrl
        material.netdisk_password = payload.netdiskPassword
        material.netdisk_expired_at = payload.netdiskExpiredAt
        material.netdisk_reminder_at = payload.netdiskReminderAt
        material.preview_watermark_enabled = bool(payload.previewWatermarkEnabled if payload.previewWatermarkEnabled is not None else material.preview_watermark_enabled)
        material.preview_source = payload.previewSource or material.preview_source or "AUTO"
        material.custom_preview_text = payload.customPreviewText
        material.copyright_owner = payload.copyrightOwner
        material.status = "VISIBLE"
        material.review_status = "APPROVED"
        material.deleted_at = None
        material.updated_at = datetime.now(UTC)

        if file_upload is not None:
            if material.file_storage_key:
                self.asset_store.delete_key(material.file_storage_key)
            key, size = self.asset_store.save_upload(material_id=material.id, slot="file", upload=file_upload)
            material.file_storage_key = key
            material.original_filename = file_upload.filename or material.original_filename
            material.file_size = size
            material.file_type = self._resolve_file_type(file_upload.filename)
        elif is_create and delivery_method == "NETDISK":
            material.file_storage_key = None
            material.original_filename = None
            material.file_size = 0
            material.file_type = "netdisk"

        if delivery_method == "NETDISK":
            material.file_storage_key = None
            material.original_filename = None if material.original_filename is None and not self._has_file(material) else material.original_filename
            material.file_size = 0 if material.file_storage_key is None else material.file_size
            material.file_type = "netdisk" if material.file_storage_key is None else material.file_type

        if previews:
            for existing_key in self._loads(material.manual_preview_keys_json):
                if not self._is_external_url(existing_key):
                    self.asset_store.delete_key(existing_key)
            preview_keys = [self.asset_store.save_upload(material_id=material.id, slot="manual-preview", upload=file)[0] for file in previews]
            material.manual_preview_keys_json = self._json_dumps(preview_keys)
        elif is_create:
            material.manual_preview_keys_json = material.manual_preview_keys_json or self._json_dumps([])

        if custom_previews:
            for existing_key in self._loads(material.custom_preview_images_json):
                if not self._is_external_url(existing_key):
                    self.asset_store.delete_key(existing_key)
            custom_keys = [self.asset_store.save_upload(material_id=material.id, slot="custom-preview", upload=file)[0] for file in custom_previews]
            material.custom_preview_images_json = self._json_dumps(custom_keys)
        elif getattr(payload, "customPreviewClear", False):
            for existing_key in self._loads(material.custom_preview_images_json):
                if not self._is_external_url(existing_key):
                    self.asset_store.delete_key(existing_key)
            material.custom_preview_images_json = self._json_dumps([])

        manual_keys = self._loads(material.manual_preview_keys_json)
        if material.preview_source == "MANUAL" and manual_keys:
            material.preview_status = "done"
            material.preview_page_count = len(manual_keys)
            material.preview_pages = len(manual_keys)
        elif (material.file_type or "").lower() == "pdf" and self._has_file(material):
            material.preview_status = "done"
            material.preview_page_count = max(int(material.preview_page_count or 0), self.settings.material_preview_pages_large)
            material.preview_pages = min(material.preview_page_count, self.settings.material_preview_pages_small)
        else:
            material.preview_status = "unsupported"
            material.preview_page_count = None
            material.preview_pages = None
        material.preview_manifest = self._json_dumps(
            {
                "status": material.preview_status,
                "pageCount": material.preview_page_count,
                "previewPages": material.preview_pages,
                "pages": [
                    {"index": index + 1, "key": key}
                    for index, key in enumerate(manual_keys)
                    if isinstance(key, str) and key.strip()
                ],
            }
        )

        if delivery_method == "FILE" and not self._has_file(material):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")
        if delivery_method == "NETDISK" and not material.netdisk_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")

    def _bootstrap(self, session: Session) -> dict[str, Any]:
        seed = self.read_repo.load_seed()
        self.material_repo.ensure_seed_bootstrap(session, seed)
        return seed

    def _resolve_current_user(self, session: Session, current_user_id: int | None) -> dict[str, Any] | None:
        if current_user_id is None:
            return None
        seed = self.read_repo.load_seed()
        seed_user = (seed.get("users") or {}).get(str(current_user_id))
        auth_user = self.auth_repo.find_user_by_id(session, current_user_id)
        if seed_user is None and auth_user is None:
            return None
        return serialize_user_snapshot(seed_user, auth_user)

    def _matches_material(
        self,
        material: MaterialRecord,
        keyword: str | None,
        school: str | None,
        college: str | None,
        major: str | None,
        tag: str | None,
        grade_value: str | None,
        course_category: str | None,
        price: str | None,
    ) -> bool:
        if keyword:
            haystack = " ".join(
                [
                    material.title or "",
                    material.description or "",
                    material.original_filename or "",
                    " ".join(self._loads(material.tags_json)),
                ]
            ).lower()
            if keyword.strip().lower() not in haystack:
                return False
        if school and material.school != school:
            return False
        if college and material.college != college:
            return False
        if major and material.major != major:
            return False
        if tag and tag not in self._loads(material.tags_json):
            return False
        if grade_value and material.grade_value != grade_value:
            return False
        if course_category and material.course_category != course_category:
            return False
        normalized_price = (price or "").strip().lower()
        if normalized_price == "free" and not material.is_free:
            return False
        if normalized_price == "paid" and material.is_free:
            return False
        return True

    def _recommendation_score(self, material: MaterialRecord, current_user: dict[str, Any] | None) -> int:
        if current_user is None:
            return 0
        score = 0
        if current_user.get("school") and current_user.get("school") == material.school:
            score += 4
        if current_user.get("college") and current_user.get("college") == material.college:
            score += 3
        if current_user.get("major") and current_user.get("major") == material.major:
            score += 5
        grade_stages = current_user.get("gradeStages") or []
        if material.grade_value and material.grade_value in grade_stages:
            score += 2
        if "经验分享" in self._loads(material.tags_json):
            score += 1
        return score

    def _load_accessible_material(
        self,
        session: Session,
        material_id: int,
        user_id: int | None,
        can_manage_all: bool,
        require_owner: bool = False,
    ) -> MaterialRecord:
        material = self._ensure_material_exists(session, material_id)
        is_owner = user_id is not None and material.uploader_id == user_id
        if require_owner and not (is_owner or can_manage_all):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该资料")
        if material.status not in VISIBLE_STATUSES and not (is_owner or can_manage_all):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        return material

    def _ensure_material_exists(self, session: Session, material_id: int) -> MaterialRecord:
        material = self.material_repo.get_material(session, material_id)
        if material is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        return material

    def _has_paid_access(self, session: Session, material: MaterialRecord, user_id: int | None, can_manage_all: bool) -> bool:
        if user_id is None:
            return False
        if material.uploader_id == user_id or can_manage_all:
            return True
        return self.material_repo.has_purchase(session, material.id, user_id)

    def _assert_can_download(self, session: Session, material: MaterialRecord, user_id: int, role_mask: int | None) -> None:
        self._assert_download_access_without_quota(session, material, user_id, role_mask)
        if material.is_free and not self.material_repo.has_purchase(session, material.id, user_id):
            self.material_repo.add_purchase(session, material_id=material.id, user_id=user_id, source="free-download")

    def _assert_download_access_without_quota(self, session: Session, material: MaterialRecord, user_id: int, role_mask: int | None) -> None:
        if material.status not in VISIBLE_STATUSES and not self._is_owner_or_admin(material, user_id, role_mask):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        if self._is_owner_or_admin(material, user_id, role_mask):
            return
        if not material.is_free and not self.material_repo.has_purchase(session, material.id, user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请先购买后再下载")

    def _consume_quota_if_needed(self, session: Session, material: MaterialRecord, user_id: int, role_mask: int | None) -> None:
        if self._should_consume_quota(material, user_id, role_mask):
            self._consume_download_quota(session, user_id, 1)

    def _should_consume_quota(self, material: MaterialRecord, user_id: int, role_mask: int | None) -> bool:
        if self._is_privileged(role_mask):
            return False
        return material.uploader_id != user_id

    def _consume_download_quota(self, session: Session, user_id: int, count: int) -> None:
        user = self._require_user(session, user_id)
        if self._is_privileged(user.role_mask):
            return
        current = DEFAULT_FREE_DOWNLOAD_QUOTA if user.free_download_quota is None else int(user.free_download_quota)
        if current < count:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="DOWNLOAD_QUOTA_EXHAUSTED")
        user.free_download_quota = current - count
        self.auth_repo.save_user(session, user)

    def _register_download(self, session: Session, material: MaterialRecord, user_id: int) -> None:
        if self.material_repo.has_download(session, material.id, user_id):
            return
        self.material_repo.add_download(session, material_id=material.id, user_id=user_id)
        material.download_count = int(material.download_count or 0) + 1
        self.material_repo.save_material(session, material)

    def _preview_image_payload(self, material_id: int, index: int, *, key: str | None, placeholder: bool) -> dict[str, Any]:
        return {
            "index": index,
            "width": 1024,
            "height": 1448,
            "img": {
                "src": self.asset_store.build_preview_url(material_id=material_id, index=index, key=key, placeholder=placeholder),
                "srcSet": None,
                "sizes": None,
            },
            "webp": None,
            "avif": None,
            "lqip": None,
        }

    def _public_custom_preview_urls(self, material_id: int, material: MaterialRecord) -> list[str]:
        urls: list[str] = []
        for index, key in enumerate(self._loads(material.custom_preview_images_json), start=1):
            if self._is_external_url(key):
                urls.append(key)
            else:
                urls.append(self.asset_store.build_public_custom_preview_url(material_id=material_id, index=index, key=key))
        return urls

    def _has_file(self, material: MaterialRecord) -> bool:
        return material_has_file(material)

    def _require_user(self, session: Session, user_id: int) -> AuthUser:
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    def _is_privileged(self, role_mask: int | None) -> bool:
        return role_mask is not None and (((role_mask & ROLE_ADMIN) == ROLE_ADMIN) or ((role_mask & ROLE_DEVELOPER) == ROLE_DEVELOPER))

    def _is_owner_or_admin(self, material: MaterialRecord, user_id: int, role_mask: int | None) -> bool:
        return material.uploader_id == user_id or self._is_privileged(role_mask)

    def _resolve_file_type(self, filename: str | None) -> str:
        if not filename or "." not in filename:
            return "zip"
        return filename.rsplit(".", 1)[1].lower()

    def _material_created_ts(self, material: MaterialRecord) -> float:
        if material.created_at is None:
            return 0.0
        return material.created_at.astimezone(UTC).timestamp() if material.created_at.tzinfo else material.created_at.timestamp()

    def _split_tags(self, value: str | None) -> list[str]:
        if not value:
            return []
        parts = [item.strip() for item in value.replace("，", ",").replace(" ", ",").split(",")]
        seen: set[str] = set()
        tags: list[str] = []
        for part in parts:
            if not part or part in seen:
                continue
            seen.add(part)
            tags.append(part)
        return tags

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return serialize_datetime(value)

    def _loads(self, raw: str | None) -> list[Any]:
        return load_json_list(raw)

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _hash_viewer_token(self, viewer_token: str | None) -> str | None:
        if not viewer_token or not viewer_token.strip():
            return None
        return hashlib.sha256(viewer_token.strip().encode("utf-8")).hexdigest()

    def _is_external_url(self, value: str | None) -> bool:
        return bool(value and (value.startswith("http://") or value.startswith("https://")))
