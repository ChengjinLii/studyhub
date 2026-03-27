from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.profile_metadata import DEFAULT_FREE_DOWNLOAD_QUOTA
from app.integrations.material_asset_store import MaterialAssetStore
from app.models.auth import AuthUser
from app.models.materials import MaterialFavoriteRecord, MaterialRatingRecord, MaterialRecord
from app.repos.auth_repo import AuthRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.admin import AdminMaterialBatchUpdatePayload
from app.schemas.materials import MaterialCreatePayload, MaterialUpdatePayload, ReviewPayload
from app.services.read_support import clamp_limit, parse_iso_datetime, serialize_user_snapshot


ROLE_ADMIN = 8
ROLE_DEVELOPER = 16
VISIBLE_STATUSES = {"VISIBLE", "visible", "", None}
DEFAULT_OUTPUT_TIMEZONE = ZoneInfo("Asia/Shanghai")


class MaterialsService:
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
        page_items = [self._to_list_item(material) for material in items[start:end]]
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

    def get_recommendations(self, session: Session, current_user_id: int | None, limit: int | None) -> list[dict[str, Any]]:
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
        return [self._to_list_item(material) for material in sliced]

    def _user_count_with_seed_fallback(self, session: Session) -> int:
        count = self.auth_repo.count_users(session)
        if count > 0:
            return count
        seed = self.read_repo.load_seed()
        users = seed.get("users") if isinstance(seed, dict) else None
        return len(users) if isinstance(users, dict) else 0

    def get_detail(self, session: Session, current_user_id: int | None, material_id: int, can_manage_all: bool = False) -> dict[str, Any]:
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, current_user_id, can_manage_all)
        purchased = self._has_paid_access(session, material, current_user_id, can_manage_all) or material.is_free
        liked = current_user_id is not None and self.material_repo.find_like(session, material_id, current_user_id) is not None
        favorited = current_user_id is not None and self.material_repo.find_favorite(session, material_id, current_user_id) is not None
        rating_record = self.material_repo.find_rating(session, material_id, current_user_id) if current_user_id is not None else None
        detail = self._to_list_item(material)
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

    def record_view(
        self,
        session: Session,
        material_id: int,
        user_id: int | None,
        can_manage_all: bool,
        viewer_token: str | None,
    ) -> int:
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, user_id, can_manage_all)
        token_hash = self._hash_viewer_token(viewer_token)
        if user_id is not None:
            existing = self.material_repo.find_view_by_user(session, material_id, user_id)
            if existing is not None:
                return int(material.view_count or 0)
            if token_hash:
                existing_by_token = self.material_repo.find_view_by_token_hash(session, material_id, token_hash)
                if existing_by_token is not None:
                    if existing_by_token.user_id is None:
                        existing_by_token.user_id = user_id
                        session.add(existing_by_token)
                        session.commit()
                    return int(material.view_count or 0)
            self.material_repo.add_view(session, material_id=material_id, user_id=user_id, viewer_token_hash=token_hash)
        elif token_hash:
            if self.material_repo.find_view_by_token_hash(session, material_id, token_hash) is not None:
                return int(material.view_count or 0)
            self.material_repo.add_view(session, material_id=material_id, user_id=None, viewer_token_hash=token_hash)
        else:
            return int(material.view_count or 0)
        material.view_count = int(material.view_count or 0) + 1
        self.material_repo.save_material(session, material)
        session.commit()
        return int(material.view_count or 0)

    def get_preview(self, session: Session, material_id: int, user_id: int, can_manage_all: bool) -> dict[str, Any]:
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
        return self.get_detail(session, operator_id, material.id, can_manage_all)

    def delete_material(self, session: Session, material_id: int, *, operator_id: int, can_manage_all: bool) -> None:
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, operator_id, can_manage_all, require_owner=True)
        material.status = "REMOVED"
        material.deleted_at = datetime.now(UTC)
        self.material_repo.save_material(session, material)
        session.commit()

    def restore_material(self, session: Session, material_id: int, *, can_manage_all: bool) -> dict[str, Any]:
        self._bootstrap(session)
        if not can_manage_all:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权恢复该资料")
        material = self._ensure_material_exists(session, material_id)
        material.status = "VISIBLE"
        material.deleted_at = None
        self.material_repo.save_material(session, material)
        session.commit()
        return self._to_admin_item(material)

    def list_for_admin(
        self,
        session: Session,
        *,
        page: int,
        size: int,
        status_value: str | None,
    ) -> dict[str, Any]:
        self._bootstrap(session)
        items = self.material_repo.list_all_materials(session)
        normalized_status = (status_value or "").strip().lower() or None
        filtered: list[MaterialRecord] = []
        for material in items:
            current_status = (material.status or "").strip().lower()
            if normalized_status:
                if current_status != normalized_status:
                    continue
            elif current_status == "removed":
                continue
            filtered.append(material)
        if normalized_status == "removed":
            filtered.sort(key=lambda item: -(item.deleted_at.timestamp() if item.deleted_at else 0))
        else:
            filtered.sort(key=lambda item: -self._material_created_ts(item))
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        start = safe_page * safe_size
        end = start + safe_size
        return {
            "items": [self._to_admin_item(item) for item in filtered[start:end]],
            "meta": {"page": safe_page, "size": safe_size, "total": len(filtered)},
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
        if self.material_repo.find_like(session, material_id, user_id) is not None:
            return int(material.like_count or 0)
        self.material_repo.add_like(session, material_id=material_id, user_id=user_id)
        material.like_count = int(material.like_count or 0) + 1
        self.material_repo.save_material(session, material)
        session.commit()
        return int(material.like_count or 0)

    def unlike(self, session: Session, material_id: int, user_id: int) -> int:
        self._bootstrap(session)
        material = self._ensure_material_exists(session, material_id)
        entity = self.material_repo.find_like(session, material_id, user_id)
        if entity is None:
            return int(material.like_count or 0)
        self.material_repo.remove_like(session, entity)
        material.like_count = max(0, int(material.like_count or 0) - 1)
        self.material_repo.save_material(session, material)
        session.commit()
        return int(material.like_count or 0)

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
        material.rating_count = next_count
        material.rating_avg = round(next_avg, 2)
        self.material_repo.save_material(session, material)
        session.commit()
        return {"ratingAvg": material.rating_avg, "ratingCount": material.rating_count, "rating": rating, "reviewer": user.nickname}

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
        self._bootstrap(session)
        material = self._load_accessible_material(session, material_id, user_id, self._is_privileged(role_mask))
        self._assert_can_download(session, material, user_id, role_mask)
        self._consume_quota_if_needed(session, material, user_id, role_mask)
        self._register_download(session, material, user_id)
        session.commit()
        if self._has_file(material):
            url, expires_at = self.asset_store.build_download_url(material_id=material.id, key=material.file_storage_key or "", filename=material.original_filename)
            return {"url": url, "expiresAt": expires_at}
        if material.netdisk_url:
            return {"url": material.netdisk_url, "expiresAt": material.netdisk_expired_at.isoformat() if material.netdisk_expired_at else None}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")

    def generate_batch_downloads(self, session: Session, material_ids: list[int], *, user_id: int, role_mask: int | None) -> list[dict[str, Any]]:
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

    def resolve_public_custom_preview_path(self, session: Session, material_id: int, index: int) -> Path:
        self._bootstrap(session)
        material = self._ensure_material_exists(session, material_id)
        keys = self._loads(material.custom_preview_images_json)
        if index < 1 or index > len(keys):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预览图片不存在")
        key = keys[index - 1]
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
            material.file_size = None
            material.file_type = None

        if delivery_method == "NETDISK":
            material.file_storage_key = None
            material.original_filename = None if material.original_filename is None and not self._has_file(material) else material.original_filename
            material.file_size = None if material.file_storage_key is None else material.file_size
            material.file_type = None if material.file_storage_key is None else material.file_type

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
        material.preview_manifest = f"materials/{material.id}/preview/manifest.json"

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

    def _to_list_item(self, material: MaterialRecord) -> dict[str, Any]:
        return {
            "id": material.id,
            "uploaderId": material.uploader_id,
            "title": material.title,
            "description": material.description,
            "price": material.price / 100.0,
            "free": bool(material.is_free),
            "school": material.school,
            "college": material.college,
            "major": material.major,
            "generalEducation": bool(material.general_course),
            "hasFile": self._has_file(material),
            "hasNetdisk": bool(material.netdisk_url),
            "courseCategory": material.course_category,
            "gradeType": material.grade_type,
            "gradeValue": material.grade_value,
            "tags": self._loads(material.tags_json),
            "previewWatermarkEnabled": material.preview_watermark_enabled,
            "previewSource": material.preview_source,
            "ratingAvg": material.rating_avg,
            "ratingCount": material.rating_count,
            "likeCount": material.like_count,
            "commentCount": material.comment_count,
            "viewCount": material.view_count,
            "downloadCount": material.download_count,
            "salesCount": material.sales_count,
            "createdAt": self._serialize_datetime(material.created_at),
            "uploaderUsername": material.uploader_username,
            "uploaderNickname": material.uploader_nickname,
            "copyrightOwner": material.copyright_owner,
        }

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
        return bool(material.file_storage_key or (material.delivery_method == "FILE" and (material.original_filename or material.file_type)))

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
        if value is None:
            return None
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=DEFAULT_OUTPUT_TIMEZONE)
        return normalized.isoformat()

    def _to_admin_item(self, material: MaterialRecord) -> dict[str, Any]:
        return {
            "id": material.id,
            "title": material.title,
            "school": material.school,
            "college": material.college,
            "major": material.major,
            "gradeValue": material.grade_value,
            "gradeType": material.grade_type,
            "courseCategory": material.course_category,
            "tags": self._loads(material.tags_json),
            "price": material.price / 100.0,
            "free": bool(material.is_free),
            "status": material.status,
            "reviewStatus": material.review_status,
            "uploaderId": material.uploader_id,
            "uploaderUsername": material.uploader_username,
            "uploaderNickname": material.uploader_nickname,
            "downloadCount": material.download_count,
            "salesCount": material.sales_count,
            "createdAt": self._serialize_datetime(material.created_at),
            "updatedAt": self._serialize_datetime(material.updated_at),
            "deletedAt": self._serialize_datetime(material.deleted_at),
        }

    def _loads(self, raw: str | None) -> list[Any]:
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:  # noqa: BLE001
            return []
        return value if isinstance(value, list) else []

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _hash_viewer_token(self, viewer_token: str | None) -> str | None:
        if not viewer_token or not viewer_token.strip():
            return None
        return hashlib.sha256(viewer_token.strip().encode("utf-8")).hexdigest()

    def _is_external_url(self, value: str | None) -> bool:
        return bool(value and (value.startswith("http://") or value.startswith("https://")))
