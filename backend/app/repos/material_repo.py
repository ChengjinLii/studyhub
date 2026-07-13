from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.orm import Session, load_only

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


_TABLE_NAME_CACHE: dict[str, set[str]] = {}
_TABLE_COLUMN_CACHE: dict[tuple[str, str], set[str]] = {}
_MATERIAL_MAPPED_COLUMNS = tuple(MaterialRecord.__table__.columns)


def _bind_cache_key(session: Session) -> str:
    bind = session.get_bind()
    try:
        url = bind.engine.url
        rendered = url.render_as_string(hide_password=True)
        if url.database in {None, ":memory:"}:
            return f"{rendered}:{id(bind)}"
        return rendered
    except Exception:
        return str(bind)


def _table_names(session: Session) -> set[str]:
    cache_key = _bind_cache_key(session)
    cached = _TABLE_NAME_CACHE.get(cache_key)
    if cached is not None:
        return cached
    inspector = inspect(session.get_bind())
    table_names = set(inspector.get_table_names())
    _TABLE_NAME_CACHE[cache_key] = table_names
    return table_names


def _table_columns(session: Session, table_name: str) -> set[str]:
    cache_key = (_bind_cache_key(session), table_name)
    cached = _TABLE_COLUMN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    inspector = inspect(session.get_bind())
    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    _TABLE_COLUMN_CACHE[cache_key] = column_names
    return column_names


def _has_table_column(session: Session, table_name: str, column_name: str) -> bool:
    return column_name in _table_columns(session, table_name)


def _material_record_load_options(session: Session):
    existing_columns = _table_columns(session, "materials")
    if all(column.name in existing_columns for column in _MATERIAL_MAPPED_COLUMNS):
        return ()
    mapped_existing_columns = tuple(
        getattr(MaterialRecord, column.name) for column in _MATERIAL_MAPPED_COLUMNS if column.name in existing_columns
    )
    return (load_only(*mapped_existing_columns),)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MaterialRepository:
    def _uses_legacy_material_likes(self, session: Session) -> bool:
        table_names = _table_names(session)
        return "material_likes" in table_names and not _has_table_column(session, "material_likes", "updated_at")

    def _uses_legacy_material_views(self, session: Session) -> bool:
        table_names = _table_names(session)
        return "material_views" in table_names and _has_table_column(session, "material_views", "viewed_at")

    def _uses_legacy_material_downloads(self, session: Session) -> bool:
        table_names = _table_names(session)
        return "material_downloads" in table_names and not _has_table_column(session, "material_downloads", "updated_at")

    def _uses_legacy_reviews(self, session: Session) -> bool:
        table_names = _table_names(session)
        return "material_reviews" not in table_names and "reviews" in table_names

    def _uses_legacy_favorites(self, session: Session) -> bool:
        table_names = _table_names(session)
        return "material_favorites" not in table_names and "favorites" in table_names

    def _uses_legacy_purchases(self, session: Session) -> bool:
        table_names = _table_names(session)
        return "material_purchases" not in table_names and "orders" in table_names

    def _legacy_purchase_exists(self, session: Session, material_id: int, user_id: int) -> bool:
        paid_order = session.execute(
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
        if paid_order is not None:
            return True
        paid_payment = session.execute(
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
        return paid_payment is not None

    def ensure_seed_bootstrap(self, session: Session, seed: dict[str, Any]) -> None:
        if not seed:
            return
        if not _has_table_column(session, "materials", "source"):
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
        stmt = (
            select(MaterialRecord)
            .options(*_material_record_load_options(session))
            .where(MaterialRecord.deleted_at.is_(None), MaterialRecord.status.not_in(("REMOVED", "HIDDEN")))
        )
        return list(session.scalars(stmt))

    def list_visible_materials_for_agent_memory(
        self,
        session: Session,
        *,
        limit: int,
    ) -> list[MaterialRecord]:
        stmt = (
            select(MaterialRecord)
            .options(*_material_record_load_options(session))
            .where(MaterialRecord.deleted_at.is_(None), MaterialRecord.status.not_in(("REMOVED", "HIDDEN")))
            .order_by(
                MaterialRecord.download_count.desc(),
                MaterialRecord.rating_avg.desc(),
                MaterialRecord.like_count.desc(),
                MaterialRecord.id.desc(),
            )
            .limit(max(1, int(limit)))
        )
        return list(session.scalars(stmt))

    def list_visible_materials_matching_text(
        self,
        session: Session,
        *,
        match_values: list[str],
        school: str | None,
        major: str | None,
        college: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
    ) -> list[MaterialRecord]:
        search_filters = self._material_text_match_filters(session, match_values=match_values)
        existing_columns = _table_columns(session, "materials")
        constraint_filters = []
        if school and "school" in existing_columns:
            constraint_filters.append(MaterialRecord.school == school)
        if college and "college" in existing_columns:
            constraint_filters.append(
                func.lower(func.coalesce(MaterialRecord.college, "")).like(
                    f"%{_escape_like(college.lower())}%",
                    escape="\\",
                )
            )
        if major and "major" in existing_columns:
            constraint_filters.append(
                func.lower(func.coalesce(MaterialRecord.major, "")).like(
                    f"%{_escape_like(major.lower())}%",
                    escape="\\",
                )
            )
        if tag and "tags_json" in existing_columns:
            constraint_filters.append(
                func.lower(func.coalesce(MaterialRecord.tags_json, "")).like(
                    f"%{_escape_like(tag.lower())}%",
                    escape="\\",
                )
            )
        if not search_filters and not constraint_filters:
            if limit is not None:
                return self.list_visible_materials_for_agent_memory(session, limit=limit)
            return self.list_visible_materials(session)
        where_filters = [
            MaterialRecord.deleted_at.is_(None),
            MaterialRecord.status.not_in(("REMOVED", "HIDDEN")),
            *constraint_filters,
        ]
        if search_filters:
            where_filters.append(or_(*search_filters))
        stmt = (
            select(MaterialRecord)
            .options(*_material_record_load_options(session))
            .where(*where_filters)
            .order_by(
                MaterialRecord.download_count.desc(),
                MaterialRecord.rating_avg.desc(),
                MaterialRecord.like_count.desc(),
                MaterialRecord.created_at.desc(),
                MaterialRecord.id.desc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(max(1, int(limit)))
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
            .options(*_material_record_load_options(session))
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

    def _material_text_match_filters(
        self,
        session: Session,
        *,
        match_values: list[str],
    ):
        existing_columns = _table_columns(session, "materials")
        filters = []
        search_column_names = (
            "title",
            "description",
            "original_filename",
            "keywords",
            "tags_json",
            "school",
            "college",
            "major",
        )
        search_columns = [
            getattr(MaterialRecord, column_name)
            for column_name in search_column_names
            if column_name in existing_columns
        ]
        normalized_values = []
        for value in match_values:
            normalized = str(value or "").strip().lower()
            if normalized and normalized not in normalized_values:
                normalized_values.append(normalized)
        for value in normalized_values:
            pattern = f"%{_escape_like(value)}%"
            filters.extend(func.lower(func.coalesce(column, "")).like(pattern, escape="\\") for column in search_columns)
        return tuple(filters)

    def count_paid_visible_materials_for_uploader(self, session: Session, uploader_id: int) -> int:
        stmt = select(func.count()).select_from(MaterialRecord).where(
            MaterialRecord.deleted_at.is_(None),
            MaterialRecord.status.not_in(("REMOVED", "HIDDEN")),
            MaterialRecord.uploader_id == uploader_id,
            MaterialRecord.is_free.is_(False),
        )
        return int(session.scalar(stmt) or 0)

    def list_all_materials(self, session: Session) -> list[MaterialRecord]:
        stmt = select(MaterialRecord).options(*_material_record_load_options(session)).order_by(MaterialRecord.created_at.desc(), MaterialRecord.id.desc())
        return list(session.scalars(stmt))

    def count_materials_for_admin(self, session: Session, *, status_value: str | None) -> int:
        stmt = select(func.count()).select_from(MaterialRecord).where(*self._admin_status_filters(status_value))
        return int(session.scalar(stmt) or 0)

    def list_materials_for_admin(
        self,
        session: Session,
        *,
        status_value: str | None,
        limit: int,
        offset: int,
    ) -> list[MaterialRecord]:
        normalized_status = self._normalize_status_filter(status_value)
        order_by = (
            (MaterialRecord.deleted_at.desc(), MaterialRecord.created_at.desc(), MaterialRecord.id.desc())
            if normalized_status == "removed"
            else (MaterialRecord.created_at.desc(), MaterialRecord.id.desc())
        )
        stmt = (
            select(MaterialRecord)
            .options(*_material_record_load_options(session))
            .where(*self._admin_status_filters(status_value))
            .order_by(*order_by)
            .limit(max(1, int(limit)))
            .offset(max(0, int(offset)))
        )
        return list(session.scalars(stmt))

    def _admin_status_filters(self, status_value: str | None):
        normalized_status = self._normalize_status_filter(status_value)
        status_expr = func.lower(func.trim(func.coalesce(MaterialRecord.status, "")))
        if normalized_status:
            return (status_expr == normalized_status,)
        return (status_expr != "removed",)

    def _normalize_status_filter(self, status_value: str | None) -> str | None:
        return (status_value or "").strip().lower() or None

    def get_material(self, session: Session, material_id: int) -> MaterialRecord | None:
        stmt = (
            select(MaterialRecord)
            .options(*_material_record_load_options(session))
            .where(MaterialRecord.id == material_id)
            .limit(1)
        )
        return session.scalar(stmt)

    def list_materials_by_ids(self, session: Session, material_ids: list[int]) -> list[MaterialRecord]:
        if not material_ids:
            return []
        stmt = (
            select(MaterialRecord)
            .options(*_material_record_load_options(session))
            .where(MaterialRecord.id.in_(sorted(set(material_ids))))
        )
        return list(session.scalars(stmt))

    def next_material_id(self, session: Session, seed: dict[str, Any]) -> int:
        seed_max = max((int(item["id"]) for item in seed.get("materials") or []), default=0)
        db_max = int(session.scalar(select(func.max(MaterialRecord.id))) or 0)
        return max(seed_max, db_max) + 1

    def save_material(self, session: Session, material: MaterialRecord) -> MaterialRecord:
        session.add(material)
        session.flush()
        existing_columns = _table_columns(session, "materials")
        if all(column.name in existing_columns for column in _MATERIAL_MAPPED_COLUMNS):
            session.refresh(material)
            return material
        refreshable_columns = [column.name for column in _MATERIAL_MAPPED_COLUMNS if column.name in existing_columns]
        if refreshable_columns:
            session.refresh(material, attribute_names=refreshable_columns)
        return material

    def list_versions(self, session: Session, material_id: int) -> list[MaterialVersionRecord]:
        stmt = (
            select(MaterialVersionRecord)
            .where(MaterialVersionRecord.material_id == material_id)
            .order_by(MaterialVersionRecord.created_at.desc(), MaterialVersionRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def add_version(self, session: Session, *, material_id: int, version_label: str, created_at: datetime | None = None) -> MaterialVersionRecord:
        existing_columns = _table_columns(session, "material_versions")
        if "file_key" in existing_columns:
            return self._add_legacy_version(session, material_id=material_id, version_label=version_label, created_at=created_at)
        entity = MaterialVersionRecord(material_id=material_id, version_label=version_label)
        if created_at is not None:
            entity.created_at = created_at
            entity.updated_at = created_at
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def _add_legacy_version(
        self,
        session: Session,
        *,
        material_id: int,
        version_label: str,
        created_at: datetime | None = None,
    ) -> MaterialVersionRecord:
        existing_columns = _table_columns(session, "material_versions")
        material = self.get_material(session, material_id)
        now = created_at or datetime.now(UTC)
        values: dict[str, Any] = {
            "material_id": material_id,
            "version_label": version_label,
            "changelog": None,
            "file_key": (material.file_storage_key if material else None) or "",
            "md_key": None,
            "encryption_password": None,
            "file_type": (material.file_type if material else None) or "zip",
            "created_at": now,
            "updated_at": now,
        }
        insert_columns = [name for name in values if name in existing_columns]
        placeholders = ", ".join(f":{name}" for name in insert_columns)
        columns_sql = ", ".join(insert_columns)
        result = session.execute(
            text(f"INSERT INTO material_versions ({columns_sql}) VALUES ({placeholders})"),
            {name: values[name] for name in insert_columns},
        )
        session.flush()
        version_id = getattr(result, "lastrowid", None)
        if version_id:
            loaded = session.get(MaterialVersionRecord, int(version_id))
            if loaded is not None:
                return loaded
        return MaterialVersionRecord(
            id=int(version_id or 0),
            material_id=material_id,
            version_label=version_label,
            created_at=now,
            updated_at=now,
        )

    def list_reviews(self, session: Session, material_id: int) -> list[MaterialReviewRecord]:
        if self._uses_legacy_reviews(session):
            rows = session.execute(
                text(
                    """
                    SELECT id, material_id, user_id, reviewer, rating, comment, created_at
                    FROM reviews
                    WHERE material_id = :material_id
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                {"material_id": material_id},
            ).mappings().all()
            return [
                MaterialReviewRecord(
                    id=int(row["id"]),
                    material_id=int(row["material_id"]),
                    user_id=int(row["user_id"]) if row["user_id"] is not None else None,
                    reviewer=str(row["reviewer"] or ""),
                    rating=int(row["rating"] or 0),
                    comment=row["comment"],
                    created_at=row["created_at"],
                    updated_at=row["created_at"],
                )
                for row in rows
            ]
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
        if self._uses_legacy_reviews(session):
            timestamp = created_at or datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO reviews (material_id, user_id, reviewer, rating, comment, created_at)
                    VALUES (:material_id, :user_id, :reviewer, :rating, :comment, :created_at)
                    """
                ),
                {
                    "material_id": material_id,
                    "user_id": user_id,
                    "reviewer": reviewer,
                    "rating": rating,
                    "comment": comment,
                    "created_at": timestamp,
                },
            )
            review_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return MaterialReviewRecord(
                id=review_id or None,
                material_id=material_id,
                user_id=user_id,
                reviewer=reviewer,
                rating=rating,
                comment=comment,
                created_at=timestamp,
                updated_at=timestamp,
            )
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
        if self._uses_legacy_material_likes(session):
            row = session.execute(
                text(
                    """
                    SELECT id, material_id, user_id, created_at
                    FROM material_likes
                    WHERE material_id = :material_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"material_id": material_id, "user_id": user_id},
            ).mappings().first()
            if row is None:
                return None
            return MaterialLikeRecord(
                id=int(row["id"]),
                material_id=int(row["material_id"]),
                user_id=int(row["user_id"]),
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        stmt = select(MaterialLikeRecord).where(MaterialLikeRecord.material_id == material_id, MaterialLikeRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_like(self, session: Session, *, material_id: int, user_id: int) -> MaterialLikeRecord:
        if self._uses_legacy_material_likes(session):
            timestamp = datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO material_likes (material_id, user_id, created_at)
                    VALUES (:material_id, :user_id, :created_at)
                    """
                ),
                {"material_id": material_id, "user_id": user_id, "created_at": timestamp},
            )
            like_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return MaterialLikeRecord(
                id=like_id or None,
                material_id=material_id,
                user_id=user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        entity = MaterialLikeRecord(material_id=material_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_like(self, session: Session, entity: MaterialLikeRecord) -> None:
        if self._uses_legacy_material_likes(session):
            if entity.id is not None:
                session.execute(text("DELETE FROM material_likes WHERE id = :id"), {"id": int(entity.id)})
            else:
                session.execute(
                    text("DELETE FROM material_likes WHERE material_id = :material_id AND user_id = :user_id"),
                    {"material_id": int(entity.material_id), "user_id": int(entity.user_id)},
                )
            return
        session.delete(entity)

    def find_favorite(self, session: Session, material_id: int, user_id: int) -> MaterialFavoriteRecord | None:
        if self._uses_legacy_favorites(session):
            row = session.execute(
                text(
                    """
                    SELECT id, material_id, user_id, created_at
                    FROM favorites
                    WHERE material_id = :material_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"material_id": material_id, "user_id": user_id},
            ).mappings().first()
            if row is None:
                return None
            return MaterialFavoriteRecord(
                id=int(row["id"]),
                material_id=int(row["material_id"]),
                user_id=int(row["user_id"]),
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        stmt = select(MaterialFavoriteRecord).where(MaterialFavoriteRecord.material_id == material_id, MaterialFavoriteRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_favorite(self, session: Session, *, material_id: int, user_id: int) -> MaterialFavoriteRecord:
        if self._uses_legacy_favorites(session):
            timestamp = datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO favorites (material_id, user_id, created_at)
                    VALUES (:material_id, :user_id, :created_at)
                    """
                ),
                {"material_id": material_id, "user_id": user_id, "created_at": timestamp},
            )
            favorite_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return MaterialFavoriteRecord(
                id=favorite_id or None,
                material_id=material_id,
                user_id=user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        entity = MaterialFavoriteRecord(material_id=material_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_favorite(self, session: Session, entity: MaterialFavoriteRecord) -> None:
        if self._uses_legacy_favorites(session):
            if entity.id is not None:
                session.execute(text("DELETE FROM favorites WHERE id = :id"), {"id": int(entity.id)})
            else:
                session.execute(
                    text("DELETE FROM favorites WHERE material_id = :material_id AND user_id = :user_id"),
                    {"material_id": int(entity.material_id), "user_id": int(entity.user_id)},
                )
            return
        session.delete(entity)

    def find_view_by_user(self, session: Session, material_id: int, user_id: int) -> MaterialViewRecord | None:
        if self._uses_legacy_material_views(session):
            row = session.execute(
                text(
                    """
                    SELECT id, material_id, user_id, viewer_token_hash, viewed_at
                    FROM material_views
                    WHERE material_id = :material_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"material_id": material_id, "user_id": user_id},
            ).mappings().first()
            return self._legacy_view_record(row)
        stmt = select(MaterialViewRecord).where(MaterialViewRecord.material_id == material_id, MaterialViewRecord.user_id == user_id)
        return session.scalar(stmt)

    def find_view_by_token_hash(self, session: Session, material_id: int, viewer_token_hash: str) -> MaterialViewRecord | None:
        if self._uses_legacy_material_views(session):
            row = session.execute(
                text(
                    """
                    SELECT id, material_id, user_id, viewer_token_hash, viewed_at
                    FROM material_views
                    WHERE material_id = :material_id AND viewer_token_hash = :viewer_token_hash
                    LIMIT 1
                    """
                ),
                {"material_id": material_id, "viewer_token_hash": viewer_token_hash},
            ).mappings().first()
            return self._legacy_view_record(row)
        stmt = select(MaterialViewRecord).where(
            MaterialViewRecord.material_id == material_id,
            MaterialViewRecord.viewer_token_hash == viewer_token_hash,
        )
        return session.scalar(stmt)

    def bind_view_to_user(self, session: Session, entity: MaterialViewRecord, user_id: int) -> None:
        if self._uses_legacy_material_views(session):
            if entity.id is not None:
                session.execute(
                    text("UPDATE material_views SET user_id = :user_id WHERE id = :id AND user_id IS NULL"),
                    {"id": int(entity.id), "user_id": user_id},
                )
            return
        entity.user_id = user_id
        session.add(entity)

    def add_view(self, session: Session, *, material_id: int, user_id: int | None, viewer_token_hash: str | None) -> MaterialViewRecord:
        if self._uses_legacy_material_views(session):
            timestamp = datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO material_views (material_id, user_id, viewer_token_hash, viewed_at)
                    VALUES (:material_id, :user_id, :viewer_token_hash, :viewed_at)
                    """
                ),
                {
                    "material_id": material_id,
                    "user_id": user_id,
                    "viewer_token_hash": viewer_token_hash,
                    "viewed_at": timestamp,
                },
            )
            view_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return MaterialViewRecord(
                id=view_id or None,
                material_id=material_id,
                user_id=user_id,
                viewer_token_hash=viewer_token_hash,
                created_at=timestamp,
                updated_at=timestamp,
            )
        entity = MaterialViewRecord(material_id=material_id, user_id=user_id, viewer_token_hash=viewer_token_hash)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def _legacy_view_record(self, row: Any) -> MaterialViewRecord | None:
        if row is None:
            return None
        return MaterialViewRecord(
            id=int(row["id"]),
            material_id=int(row["material_id"]),
            user_id=None if row["user_id"] is None else int(row["user_id"]),
            viewer_token_hash=row["viewer_token_hash"],
            created_at=row["viewed_at"],
            updated_at=row["viewed_at"],
        )

    def has_download(self, session: Session, material_id: int, user_id: int) -> bool:
        stmt = select(MaterialDownloadRecord.id).where(MaterialDownloadRecord.material_id == material_id, MaterialDownloadRecord.user_id == user_id)
        return session.scalar(stmt) is not None

    def add_download(self, session: Session, *, material_id: int, user_id: int) -> MaterialDownloadRecord:
        if self._uses_legacy_material_downloads(session):
            timestamp = datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO material_downloads (material_id, user_id, created_at)
                    VALUES (:material_id, :user_id, :created_at)
                    """
                ),
                {"material_id": material_id, "user_id": user_id, "created_at": timestamp},
            )
            download_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return MaterialDownloadRecord(
                id=download_id or None,
                material_id=material_id,
                user_id=user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        entity = MaterialDownloadRecord(material_id=material_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def has_purchase(self, session: Session, material_id: int, user_id: int) -> bool:
        if self._uses_legacy_purchases(session):
            return self._legacy_purchase_exists(session, material_id, user_id)
        stmt = select(MaterialPurchaseRecord.id).where(MaterialPurchaseRecord.material_id == material_id, MaterialPurchaseRecord.user_id == user_id)
        return session.scalar(stmt) is not None

    def add_purchase(self, session: Session, *, material_id: int, user_id: int, source: str) -> MaterialPurchaseRecord:
        if self._uses_legacy_purchases(session):
            return MaterialPurchaseRecord(material_id=material_id, user_id=user_id, source=source)
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
