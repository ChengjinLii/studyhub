from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session, load_only

from app.models.comments import CommentLikeRecord, CommentRecord


_TABLE_COLUMN_CACHE: dict[tuple[str, str], set[str]] = {}
_COMMENT_MAPPED_COLUMNS = tuple(CommentRecord.__table__.columns)


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


def _comment_record_load_options(session: Session):
    existing_columns = _table_columns(session, "comments")
    if all(column.name in existing_columns for column in _COMMENT_MAPPED_COLUMNS):
        return ()
    mapped_existing_columns = tuple(
        getattr(CommentRecord, column.name)
        for column in _COMMENT_MAPPED_COLUMNS
        if column.name in existing_columns
    )
    return (load_only(*mapped_existing_columns),)


class CommentRepository:
    def _uses_legacy_comment_likes(self, session: Session) -> bool:
        return "comment_likes" in inspect(session.get_bind()).get_table_names() and not _has_table_column(session, "comment_likes", "updated_at")

    def ensure_seed_bootstrap(self, session: Session, seed: dict[str, Any]) -> None:
        if not seed:
            return
        if not _has_table_column(session, "comments", "source"):
            return
        seed_comments = seed.get("comments") or []
        seed_count = int(session.scalar(select(func.count()).select_from(CommentRecord).where(CommentRecord.source == "seed")) or 0)
        if seed_count >= len(seed_comments) and seed_count > 0:
            return

        for item in seed_comments:
            comment_id = int(item["id"])
            entity = session.get(CommentRecord, comment_id)
            if entity is None:
                entity = CommentRecord(
                    id=comment_id,
                    source="seed",
                    material_id=int(item["materialId"]),
                    parent_id=int(item["parentId"]) if item.get("parentId") is not None else None,
                    user_id=int(item["userId"]),
                    user_nickname=item.get("nickname"),
                    user_avatar=item.get("avatar"),
                    content=item.get("content") or "",
                    like_count=int(item.get("likeCount", 0) or 0),
                    reply_count=int(item.get("replyCount", 0) or 0),
                    edited=bool(item.get("edited")),
                    status=item.get("status") or "visible",
                    rating=int(item["rating"]) if item.get("rating") is not None else None,
                    created_at=self._parse_datetime(item.get("createdAt")),
                    updated_at=self._parse_datetime(item.get("updatedAt")) or self._parse_datetime(item.get("createdAt")),
                )
                session.add(entity)

        for user_id, comment_ids in ((seed.get("relationships") or {}).get("commentLikes") or {}).items():
            for comment_id in comment_ids:
                if self.find_like(session, int(comment_id), int(user_id)) is None:
                    session.add(CommentLikeRecord(comment_id=int(comment_id), user_id=int(user_id)))
        session.flush()

    def list_comments(self, session: Session, *, material_id: int, parent_id: int | None, visible_only: bool) -> list[CommentRecord]:
        stmt = select(CommentRecord).options(*_comment_record_load_options(session)).where(CommentRecord.material_id == material_id)
        if parent_id is None:
            stmt = stmt.where(CommentRecord.parent_id.is_(None))
        else:
            stmt = stmt.where(CommentRecord.parent_id == parent_id)
        if visible_only:
            stmt = stmt.where(CommentRecord.status == "visible")
        stmt = stmt.order_by(CommentRecord.created_at.desc(), CommentRecord.id.desc())
        return list(session.scalars(stmt))

    def get_comment(self, session: Session, comment_id: int) -> CommentRecord | None:
        stmt = select(CommentRecord).options(*_comment_record_load_options(session)).where(CommentRecord.id == comment_id).limit(1)
        return session.scalar(stmt)

    def list_comments_by_ids(self, session: Session, comment_ids: list[int]) -> list[CommentRecord]:
        if not comment_ids:
            return []
        stmt = select(CommentRecord).options(*_comment_record_load_options(session)).where(CommentRecord.id.in_(sorted(set(comment_ids))))
        return list(session.scalars(stmt))

    def save_comment(self, session: Session, entity: CommentRecord) -> CommentRecord:
        session.add(entity)
        session.flush()
        existing_columns = _table_columns(session, "comments")
        if all(column.name in existing_columns for column in _COMMENT_MAPPED_COLUMNS):
            session.refresh(entity)
            return entity
        refreshable_columns = [column.name for column in _COMMENT_MAPPED_COLUMNS if column.name in existing_columns]
        if refreshable_columns:
            session.refresh(entity, attribute_names=refreshable_columns)
        return entity

    def find_like(self, session: Session, comment_id: int, user_id: int) -> CommentLikeRecord | None:
        if self._uses_legacy_comment_likes(session):
            row = session.execute(
                text(
                    """
                    SELECT id, comment_id, user_id, created_at
                    FROM comment_likes
                    WHERE comment_id = :comment_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"comment_id": comment_id, "user_id": user_id},
            ).mappings().first()
            if row is None:
                return None
            return CommentLikeRecord(
                id=int(row["id"]),
                comment_id=int(row["comment_id"]),
                user_id=int(row["user_id"]),
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        stmt = select(CommentLikeRecord).where(CommentLikeRecord.comment_id == comment_id, CommentLikeRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_like(self, session: Session, *, comment_id: int, user_id: int) -> CommentLikeRecord:
        if self._uses_legacy_comment_likes(session):
            timestamp = datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO comment_likes (comment_id, user_id, created_at)
                    VALUES (:comment_id, :user_id, :created_at)
                    """
                ),
                {"comment_id": comment_id, "user_id": user_id, "created_at": timestamp},
            )
            like_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return CommentLikeRecord(
                id=like_id or None,
                comment_id=comment_id,
                user_id=user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        entity = CommentLikeRecord(comment_id=comment_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_like(self, session: Session, entity: CommentLikeRecord) -> None:
        if self._uses_legacy_comment_likes(session):
            if entity.id is not None:
                session.execute(text("DELETE FROM comment_likes WHERE id = :id"), {"id": int(entity.id)})
            else:
                session.execute(
                    text("DELETE FROM comment_likes WHERE comment_id = :comment_id AND user_id = :user_id"),
                    {"comment_id": int(entity.comment_id), "user_id": int(entity.user_id)},
                )
            return
        session.delete(entity)

    def liked_comment_ids(self, session: Session, *, comment_ids: list[int], user_id: int | None) -> set[int]:
        if user_id is None or not comment_ids:
            return set()
        stmt = select(CommentLikeRecord.comment_id).where(CommentLikeRecord.user_id == user_id, CommentLikeRecord.comment_id.in_(comment_ids))
        return {int(value) for value in session.scalars(stmt)}

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
