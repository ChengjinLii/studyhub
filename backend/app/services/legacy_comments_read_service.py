from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.services.read_support import paginate_zero_based


class LegacyCommentsReadService:
    def list_comments(
        self,
        session: Session,
        material_id: int,
        *,
        sort: str,
        page: int,
        size: int,
        current_user_id: int | None,
    ) -> dict[str, Any]:
        self._ensure_material_exists(session, material_id)
        total = int(
            session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM comments
                    WHERE material_id = :material_id
                      AND parent_id IS NULL
                      AND status = 'visible'
                    """
                ),
                {"material_id": material_id},
            ).scalar()
            or 0
        )
        rows = self._load_comment_rows(
            session,
            material_id=material_id,
            parent_id=None,
            sort=sort,
            page=page,
            size=size,
        )
        liked_ids = self._load_liked_ids(session, current_user_id, [int(row["id"]) for row in rows])
        items = [self._to_comment_item(row, int(row["id"]) in liked_ids) for row in rows]
        _, meta = paginate_zero_based(list(range(total)), page=page, size=size)
        meta["total"] = total
        return {"items": items, "meta": meta}

    def list_replies(
        self,
        session: Session,
        parent_id: int,
        *,
        page: int,
        size: int,
        current_user_id: int | None,
    ) -> dict[str, Any]:
        parent = session.execute(
            text(
                """
                SELECT id, material_id
                FROM comments
                WHERE id = :parent_id
                LIMIT 1
                """
            ),
            {"parent_id": parent_id},
        ).mappings().first()
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        total = int(
            session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM comments
                    WHERE parent_id = :parent_id
                      AND status = 'visible'
                    """
                ),
                {"parent_id": parent_id},
            ).scalar()
            or 0
        )
        rows = self._load_comment_rows(
            session,
            material_id=int(parent["material_id"]),
            parent_id=parent_id,
            sort="oldest",
            page=page,
            size=size,
        )
        liked_ids = self._load_liked_ids(session, current_user_id, [int(row["id"]) for row in rows])
        items = [self._to_comment_item(row, int(row["id"]) in liked_ids) for row in rows]
        _, meta = paginate_zero_based(list(range(total)), page=page, size=size)
        meta["total"] = total
        return {"items": items, "meta": meta}

    def _ensure_material_exists(self, session: Session, material_id: int) -> None:
        exists = session.execute(
            text(
                """
                SELECT 1
                FROM materials
                WHERE id = :material_id
                LIMIT 1
                """
            ),
            {"material_id": material_id},
        ).scalar()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

    def _load_comment_rows(
        self,
        session: Session,
        *,
        material_id: int,
        parent_id: int | None,
        sort: str,
        page: int,
        size: int,
    ) -> list[dict[str, Any]]:
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        params: dict[str, Any] = {
            "material_id": material_id,
            "limit": safe_size,
            "offset": safe_page * safe_size,
        }
        if parent_id is None:
            parent_filter = "c.parent_id IS NULL"
        else:
            parent_filter = "c.parent_id = :parent_id"
            params["parent_id"] = parent_id
        if (sort or "latest").lower() == "hottest":
            order_clause = "c.like_count DESC, c.created_at DESC"
        elif (sort or "").lower() == "oldest":
            order_clause = "c.created_at ASC, c.id ASC"
        else:
            order_clause = "c.created_at DESC, c.id DESC"
        rows = session.execute(
            text(
                f"""
                SELECT
                    c.id,
                    c.material_id,
                    c.parent_id,
                    c.user_id,
                    c.content,
                    c.like_count,
                    c.reply_count,
                    c.status,
                    c.is_edited,
                    c.created_at,
                    c.updated_at,
                    u.nickname AS user_nickname,
                    u.username AS user_username,
                    u.avatar AS user_avatar,
                    m.uploader_id,
                    r.rating
                FROM comments c
                LEFT JOIN users u ON u.id = c.user_id
                LEFT JOIN materials m ON m.id = c.material_id
                LEFT JOIN reviews r
                  ON r.material_id = c.material_id
                 AND r.user_id = c.user_id
                WHERE c.material_id = :material_id
                  AND {parent_filter}
                  AND c.status = 'visible'
                ORDER BY {order_clause}
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def _load_liked_ids(self, session: Session, current_user_id: int | None, comment_ids: list[int]) -> set[int]:
        if current_user_id is None or not comment_ids:
            return set()
        stmt = text(
            """
            SELECT comment_id
            FROM comment_likes
            WHERE user_id = :user_id
              AND comment_id IN :comment_ids
            """
        ).bindparams(bindparam("comment_ids", expanding=True))
        rows = session.execute(stmt, {"user_id": current_user_id, "comment_ids": comment_ids}).scalars().all()
        return {int(value) for value in rows}

    def _to_comment_item(self, row: dict[str, Any], has_liked: bool) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "materialId": int(row["material_id"]),
            "parentId": int(row["parent_id"]) if row["parent_id"] is not None else None,
            "content": row["content"] or "",
            "likeCount": int(row["like_count"] or 0),
            "replyCount": int(row["reply_count"] or 0),
            "edited": bool(row["is_edited"]),
            "deleted": str(row.get("status") or "").lower() != "visible",
            "createdAt": self._serialize_datetime(row["created_at"]),
            "updatedAt": self._serialize_datetime(row["updated_at"]),
            "user": {
                "id": int(row["user_id"]) if row["user_id"] is not None else None,
                "nickname": row["user_nickname"] or row["user_username"],
                "avatar": row["user_avatar"],
                "isAuthor": row["uploader_id"] is not None and row["user_id"] == row["uploader_id"],
            },
            "hasLiked": has_liked,
            "rating": int(row["rating"]) if row["rating"] is not None else None,
            "replies": [],
        }

    def _serialize_datetime(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            else:
                value = value.astimezone(UTC)
            return value.isoformat().replace("+00:00", "Z")
        return str(value)
