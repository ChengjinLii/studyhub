from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.comments import CommentLikeRecord, CommentRecord


class CommentRepository:
    def ensure_seed_bootstrap(self, session: Session, seed: dict[str, Any]) -> None:
        if not seed:
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
        stmt = select(CommentRecord).where(CommentRecord.material_id == material_id)
        if parent_id is None:
            stmt = stmt.where(CommentRecord.parent_id.is_(None))
        else:
            stmt = stmt.where(CommentRecord.parent_id == parent_id)
        if visible_only:
            stmt = stmt.where(CommentRecord.status == "visible")
        stmt = stmt.order_by(CommentRecord.created_at.desc(), CommentRecord.id.desc())
        return list(session.scalars(stmt))

    def get_comment(self, session: Session, comment_id: int) -> CommentRecord | None:
        return session.get(CommentRecord, comment_id)

    def list_comments_by_ids(self, session: Session, comment_ids: list[int]) -> list[CommentRecord]:
        if not comment_ids:
            return []
        stmt = select(CommentRecord).where(CommentRecord.id.in_(sorted(set(comment_ids))))
        return list(session.scalars(stmt))

    def save_comment(self, session: Session, entity: CommentRecord) -> CommentRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_like(self, session: Session, comment_id: int, user_id: int) -> CommentLikeRecord | None:
        stmt = select(CommentLikeRecord).where(CommentLikeRecord.comment_id == comment_id, CommentLikeRecord.user_id == user_id)
        return session.scalar(stmt)

    def add_like(self, session: Session, *, comment_id: int, user_id: int) -> CommentLikeRecord:
        entity = CommentLikeRecord(comment_id=comment_id, user_id=user_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def remove_like(self, session: Session, entity: CommentLikeRecord) -> None:
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
