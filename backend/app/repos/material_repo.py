from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.materials import (
    MaterialDownloadRecord,
    MaterialFavoriteRecord,
    MaterialLikeRecord,
    MaterialPurchaseRecord,
    MaterialRatingRecord,
    MaterialRecord,
    MaterialReviewRecord,
    MaterialVersionRecord,
    MaterialViewRecord,
)


class MaterialRepository:
    def ensure_seed_bootstrap(self, session: Session, seed: dict[str, Any]) -> None:
        if not seed:
            return
        users = seed.get("users") or {}
        materials = seed.get("materials") or []
        relationships = seed.get("relationships") or {}
        seed_material_count = int(
            session.scalar(select(func.count()).select_from(MaterialRecord).where(MaterialRecord.source == "seed")) or 0
        )

        # Seed 只做一次性导入。后续请求如果再按 seed 关系回填，会把真实的点赞/收藏/评分写操作覆盖掉。
        if seed_material_count >= len(materials) and seed_material_count > 0:
            return

        for item in materials:
            material_id = int(item["id"])
            material = session.get(MaterialRecord, material_id)
            if material is None:
                uploader_id = item.get("uploaderId")
                material = MaterialRecord(
                    id=material_id,
                    source="seed",
                    uploader_id=int(uploader_id) if uploader_id is not None else None,
                    uploader_username=item.get("uploaderUsername"),
                    uploader_nickname=item.get("uploaderNickname"),
                    title=item.get("title") or "",
                    description=item.get("description"),
                    original_filename=item.get("originalFilename"),
                    file_type=(item.get("fileType") or "").lower() or None,
                    file_size=int(item.get("fileSize")) if item.get("fileSize") is not None else None,
                    price=int(round(float(item.get("price", 0)) * 100)),
                    is_free=bool(item.get("free")),
                    school=item.get("school"),
                    college=item.get("college"),
                    major=item.get("major"),
                    general_course=bool(item.get("generalEducation")),
                    course_category=item.get("courseCategory"),
                    grade_type=item.get("gradeType"),
                    grade_value=item.get("gradeValue"),
                    keywords=item.get("keywords"),
                    tags_json=self._json_dumps(item.get("tags") or []),
                    delivery_method="NETDISK" if item.get("hasNetdisk") and not item.get("hasFile") else "FILE",
                    netdisk_url=item.get("netdiskUrl"),
                    netdisk_password=item.get("netdiskPassword"),
                    netdisk_expired_at=self._parse_date(item.get("netdiskExpiredAt")),
                    netdisk_reminder_at=self._parse_date(item.get("netdiskReminderAt")),
                    preview_watermark_enabled=bool(item.get("previewWatermarkEnabled", True)),
                    preview_source=item.get("previewSource") or "AUTO",
                    preview_manifest=item.get("previewManifest"),
                    preview_status="done" if item.get("previewSource") == "MANUAL" or (item.get("fileType") or "").lower() == "pdf" else "unsupported",
                    preview_page_count=max(len(item.get("customPreviewImages") or []), 5 if (item.get("fileType") or "").lower() == "pdf" else 0) or None,
                    preview_pages=max(
                        len(item.get("customPreviewImages") or []),
                        3 if (item.get("fileType") or "").lower() == "pdf" else 0,
                    )
                    or None,
                    manual_preview_keys_json=self._json_dumps([]),
                    custom_preview_text=item.get("customPreviewText"),
                    custom_preview_images_json=self._json_dumps(item.get("customPreviewImages") or []),
                    copyright_owner=item.get("copyrightOwner"),
                    status=item.get("status") or "VISIBLE",
                    review_status=item.get("reviewStatus"),
                    view_count=int(item.get("viewCount", 0) or 0),
                    download_count=int(item.get("downloadCount", 0) or 0),
                    sales_count=int(item.get("salesCount", 0) or 0),
                    like_count=int(item.get("likeCount", 0) or 0),
                    comment_count=int(item.get("commentCount", 0) or 0),
                    rating_avg=float(item.get("ratingAvg", 0) or 0),
                    rating_count=int(item.get("ratingCount", 0) or 0),
                    created_at=self._parse_datetime(item.get("createdAt")),
                    updated_at=self._parse_datetime(item.get("createdAt")),
                )
                session.add(material)

            if not self.list_versions(session, material_id):
                for version in item.get("versions") or []:
                    entity = MaterialVersionRecord(
                        material_id=material_id,
                        version_label=version.get("versionLabel") or "v1.0",
                        created_at=self._parse_datetime(version.get("createdAt")) or material.created_at,
                        updated_at=self._parse_datetime(version.get("createdAt")) or material.created_at,
                    )
                    session.add(entity)

            if not self.list_reviews(session, material_id):
                for review in item.get("reviews") or []:
                    entity = MaterialReviewRecord(
                        id=int(review["id"]) if review.get("id") is not None else None,
                        material_id=material_id,
                        user_id=None,
                        reviewer=review.get("reviewer") or "匿名同学",
                        rating=int(review.get("rating", 0) or 0),
                        comment=review.get("comment"),
                        created_at=self._parse_datetime(review.get("createdAt")) or material.created_at,
                        updated_at=self._parse_datetime(review.get("createdAt")) or material.created_at,
                    )
                    session.add(entity)

        for user_id, material_ids in (relationships.get("materialLikes") or {}).items():
            for material_id in material_ids:
                if self.find_like(session, int(material_id), int(user_id)) is None:
                    session.add(MaterialLikeRecord(material_id=int(material_id), user_id=int(user_id)))

        for user_id, material_ids in (relationships.get("materialFavorites") or {}).items():
            for material_id in material_ids:
                if self.find_favorite(session, int(material_id), int(user_id)) is None:
                    session.add(MaterialFavoriteRecord(material_id=int(material_id), user_id=int(user_id)))

        for user_id, ratings in (relationships.get("materialRatings") or {}).items():
            for material_id, rating in (ratings or {}).items():
                if self.find_rating(session, int(material_id), int(user_id)) is None:
                    session.add(MaterialRatingRecord(material_id=int(material_id), user_id=int(user_id), rating=int(rating)))

        for user_id, material_ids in (relationships.get("materialPurchases") or {}).items():
            for material_id in material_ids:
                if not self.has_purchase(session, int(material_id), int(user_id)):
                    session.add(MaterialPurchaseRecord(material_id=int(material_id), user_id=int(user_id), source="seed"))

        for user_id, snapshot in users.items():
            # 只为了让导入代码与 seed 对齐；当前不把用户单独写进 material 表。
            _ = (user_id, snapshot)

        session.flush()

    def list_visible_materials(self, session: Session) -> list[MaterialRecord]:
        stmt = select(MaterialRecord).where(MaterialRecord.deleted_at.is_(None), MaterialRecord.status.not_in(("REMOVED", "HIDDEN")))
        return list(session.scalars(stmt))

    def list_visible_materials_for_uploader(
        self,
        session: Session,
        uploader_id: int,
        *,
        limit: int | None = None,
    ) -> list[MaterialRecord]:
        stmt = (
            select(MaterialRecord)
            .where(
                MaterialRecord.deleted_at.is_(None),
                MaterialRecord.status.not_in(("REMOVED", "HIDDEN")),
                MaterialRecord.uploader_id == uploader_id,
            )
            .order_by(MaterialRecord.download_count.desc(), MaterialRecord.created_at.desc(), MaterialRecord.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def count_visible_materials_for_uploader(self, session: Session, uploader_id: int) -> int:
        stmt = select(func.count()).select_from(MaterialRecord).where(
            MaterialRecord.deleted_at.is_(None),
            MaterialRecord.status.not_in(("REMOVED", "HIDDEN")),
            MaterialRecord.uploader_id == uploader_id,
        )
        return int(session.scalar(stmt) or 0)

    def count_paid_visible_materials_for_uploader(self, session: Session, uploader_id: int) -> int:
        stmt = select(func.count()).select_from(MaterialRecord).where(
            MaterialRecord.deleted_at.is_(None),
            MaterialRecord.status.not_in(("REMOVED", "HIDDEN")),
            MaterialRecord.uploader_id == uploader_id,
            MaterialRecord.is_free.is_(False),
        )
        return int(session.scalar(stmt) or 0)

    def list_all_materials(self, session: Session) -> list[MaterialRecord]:
        stmt = select(MaterialRecord).order_by(MaterialRecord.created_at.desc(), MaterialRecord.id.desc())
        return list(session.scalars(stmt))

    def get_material(self, session: Session, material_id: int) -> MaterialRecord | None:
        return session.get(MaterialRecord, material_id)

    def next_material_id(self, session: Session, seed: dict[str, Any]) -> int:
        seed_max = max((int(item["id"]) for item in seed.get("materials") or []), default=0)
        db_max = int(session.scalar(select(func.max(MaterialRecord.id))) or 0)
        return max(seed_max, db_max) + 1

    def save_material(self, session: Session, material: MaterialRecord) -> MaterialRecord:
        session.add(material)
        session.flush()
        session.refresh(material)
        return material

    def list_versions(self, session: Session, material_id: int) -> list[MaterialVersionRecord]:
        stmt = (
            select(MaterialVersionRecord)
            .where(MaterialVersionRecord.material_id == material_id)
            .order_by(MaterialVersionRecord.created_at.desc(), MaterialVersionRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def add_version(self, session: Session, *, material_id: int, version_label: str, created_at: datetime | None = None) -> MaterialVersionRecord:
        entity = MaterialVersionRecord(material_id=material_id, version_label=version_label)
        if created_at is not None:
            entity.created_at = created_at
            entity.updated_at = created_at
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def list_reviews(self, session: Session, material_id: int) -> list[MaterialReviewRecord]:
        stmt = (
            select(MaterialReviewRecord)
            .where(MaterialReviewRecord.material_id == material_id)
            .order_by(MaterialReviewRecord.created_at.desc(), MaterialReviewRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def add_review(
        self,
        session: Session,
        *,
        material_id: int,
        user_id: int | None,
        reviewer: str,
        rating: int,
        comment: str | None,
        created_at: datetime | None = None,
    ) -> MaterialReviewRecord:
        entity = MaterialReviewRecord(
            material_id=material_id,
            user_id=user_id,
            reviewer=reviewer,
            rating=rating,
            comment=comment,
        )
        if created_at is not None:
            entity.created_at = created_at
            entity.updated_at = created_at
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_rating(self, session: Session, material_id: int, user_id: int) -> MaterialRatingRecord | None:
        stmt = select(MaterialRatingRecord).where(MaterialRatingRecord.material_id == material_id, MaterialRatingRecord.user_id == user_id)
        return session.scalar(stmt)

    def save_rating(self, session: Session, entity: MaterialRatingRecord) -> MaterialRatingRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_like(self, session: Session, material_id: int, user_id: int) -> MaterialLikeRecord | None:
        stmt = select(MaterialLikeRecord).where(MaterialLikeRecord.material_id == material_id, MaterialLikeRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_like(self, session: Session, *, material_id: int, user_id: int) -> MaterialLikeRecord:
        entity = MaterialLikeRecord(material_id=material_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_like(self, session: Session, entity: MaterialLikeRecord) -> None:
        session.delete(entity)

    def find_favorite(self, session: Session, material_id: int, user_id: int) -> MaterialFavoriteRecord | None:
        stmt = select(MaterialFavoriteRecord).where(MaterialFavoriteRecord.material_id == material_id, MaterialFavoriteRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_favorite(self, session: Session, *, material_id: int, user_id: int) -> MaterialFavoriteRecord:
        entity = MaterialFavoriteRecord(material_id=material_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_favorite(self, session: Session, entity: MaterialFavoriteRecord) -> None:
        session.delete(entity)

    def find_view_by_user(self, session: Session, material_id: int, user_id: int) -> MaterialViewRecord | None:
        stmt = select(MaterialViewRecord).where(MaterialViewRecord.material_id == material_id, MaterialViewRecord.user_id == user_id)
        return session.scalar(stmt)

    def find_view_by_token_hash(self, session: Session, material_id: int, viewer_token_hash: str) -> MaterialViewRecord | None:
        stmt = select(MaterialViewRecord).where(
            MaterialViewRecord.material_id == material_id,
            MaterialViewRecord.viewer_token_hash == viewer_token_hash,
        )
        return session.scalar(stmt)

    def add_view(self, session: Session, *, material_id: int, user_id: int | None, viewer_token_hash: str | None) -> MaterialViewRecord:
        entity = MaterialViewRecord(material_id=material_id, user_id=user_id, viewer_token_hash=viewer_token_hash)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def has_download(self, session: Session, material_id: int, user_id: int) -> bool:
        stmt = select(MaterialDownloadRecord.id).where(MaterialDownloadRecord.material_id == material_id, MaterialDownloadRecord.user_id == user_id)
        return session.scalar(stmt) is not None

    def add_download(self, session: Session, *, material_id: int, user_id: int) -> MaterialDownloadRecord:
        entity = MaterialDownloadRecord(material_id=material_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def has_purchase(self, session: Session, material_id: int, user_id: int) -> bool:
        stmt = select(MaterialPurchaseRecord.id).where(MaterialPurchaseRecord.material_id == material_id, MaterialPurchaseRecord.user_id == user_id)
        return session.scalar(stmt) is not None

    def add_purchase(self, session: Session, *, material_id: int, user_id: int, source: str) -> MaterialPurchaseRecord:
        entity = MaterialPurchaseRecord(material_id=material_id, user_id=user_id, source=source)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)

    def _parse_date(self, value: str | None):
        if not value:
            return None
        return datetime.fromisoformat(f"{value}T00:00:00+00:00").date()
