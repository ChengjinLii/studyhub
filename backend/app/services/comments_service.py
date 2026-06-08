from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.async_db import async_session_scope
from app.core.config import Settings
from app.models.comments import CommentRecord
from app.repos.auth_repo import AuthRepository
from app.repos.comment_repo import CommentRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.comments import CommentCreatePayload, CommentReportPayload, CommentUpdatePayload
from app.services.read_support import compat_serialize_datetime, paginate_zero_based, parse_iso_datetime, serialize_datetime


class CommentsService:
    def __init__(
        self,
        settings: Settings,
        read_repo: ReadApiRepository,
        auth_repo: AuthRepository,
        material_repo: MaterialRepository,
        comment_repo: CommentRepository,
        report_service,
    ) -> None:
        self.settings = settings
        self.read_repo = read_repo
        self.auth_repo = auth_repo
        self.material_repo = material_repo
        self.comment_repo = comment_repo
        self.report_service = report_service

    def list_comments(self, session: Session, material_id: int, *, sort: str, page: int, size: int, current_user_id: int | None) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_list_comments(
                session,
                material_id,
                sort=sort,
                page=page,
                size=size,
                current_user_id=current_user_id,
            )
        material = self._ensure_material(session, material_id)
        comments = self._serialize_comments(
            session,
            self.comment_repo.list_comments(session, material_id=material_id, parent_id=None, visible_only=True),
            current_user_id=current_user_id,
            material_uploader_id=material.uploader_id or 0,
        )
        comments.sort(key=self._resolve_sort(sort))
        items, meta = paginate_zero_based(comments, page=page, size=size)
        return {"items": items, "meta": meta}

    async def list_comments_async(
        self,
        session: Session,
        material_id: int,
        *,
        sort: str,
        page: int,
        size: int,
        current_user_id: int | None,
    ) -> dict[str, Any]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(
                self.list_comments,
                session,
                material_id,
                sort=sort,
                page=page,
                size=size,
                current_user_id=current_user_id,
            )

        await self._call_with_new_async_session(self._compat_ensure_material_exists_async, material_id)
        total, rows = await asyncio.gather(
            self._call_with_new_async_session(self._compat_count_comments_async, material_id=material_id, parent_id=None),
            self._call_with_new_async_session(
                self._compat_load_comment_rows_async,
                material_id=material_id,
                parent_id=None,
                sort=sort,
                page=page,
                size=size,
            ),
        )
        comment_ids = [int(row["id"]) for row in rows]
        liked_ids = (
            set()
            if current_user_id is None or not comment_ids
            else await self._call_with_new_async_session(
                self._compat_load_liked_ids_async,
                current_user_id,
                comment_ids,
            )
        )
        items = [self._compat_to_comment_item(row, int(row["id"]) in liked_ids) for row in rows]
        _, meta = paginate_zero_based(list(range(total)), page=page, size=size)
        meta["total"] = total
        return {"items": items, "meta": meta}

    def list_replies(self, session: Session, parent_id: int, *, page: int, size: int, current_user_id: int | None) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_list_replies(
                session,
                parent_id,
                page=page,
                size=size,
                current_user_id=current_user_id,
            )
        self._bootstrap(session)
        parent = self.comment_repo.get_comment(session, parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        material = self._ensure_material(session, parent.material_id)
        replies = self._serialize_comments(
            session,
            self.comment_repo.list_comments(session, material_id=parent.material_id, parent_id=parent_id, visible_only=True),
            current_user_id=current_user_id,
            material_uploader_id=material.uploader_id or 0,
        )
        replies.sort(key=lambda item: parse_iso_datetime(item.get("createdAt")))
        items, meta = paginate_zero_based(replies, page=page, size=size)
        return {"items": items, "meta": meta}

    async def list_replies_async(
        self,
        session: Session,
        parent_id: int,
        *,
        page: int,
        size: int,
        current_user_id: int | None,
    ) -> dict[str, Any]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(
                self.list_replies,
                session,
                parent_id,
                page=page,
                size=size,
                current_user_id=current_user_id,
            )

        parent = await self._call_with_new_async_session(self._compat_load_comment_parent_async, parent_id)
        total, rows = await asyncio.gather(
            self._call_with_new_async_session(self._compat_count_comments_async, material_id=None, parent_id=parent_id),
            self._call_with_new_async_session(
                self._compat_load_comment_rows_async,
                material_id=int(parent["material_id"]),
                parent_id=parent_id,
                sort="oldest",
                page=page,
                size=size,
            ),
        )
        comment_ids = [int(row["id"]) for row in rows]
        liked_ids = (
            set()
            if current_user_id is None or not comment_ids
            else await self._call_with_new_async_session(
                self._compat_load_liked_ids_async,
                current_user_id,
                comment_ids,
            )
        )
        items = [self._compat_to_comment_item(row, int(row["id"]) in liked_ids) for row in rows]
        _, meta = paginate_zero_based(list(range(total)), page=page, size=size)
        meta["total"] = total
        return {"items": items, "meta": meta}

    def create(self, session: Session, payload: CommentCreatePayload, user_id: int) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_create_comment(session, payload, user_id)
        material = self._ensure_material(session, payload.materialId)
        user = self._require_user(session, user_id)
        parent = None
        if payload.parentId is not None:
            parent = self.comment_repo.get_comment(session, payload.parentId)
            if parent is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标评论不存在")
            if parent.material_id != material.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="评论不属于当前资料")
        rating_record = self.material_repo.find_rating(session, material.id, user_id)
        entity = CommentRecord(
            material_id=material.id,
            parent_id=parent.id if parent else None,
            user_id=user.id,
            user_nickname=user.nickname or user.username,
            user_avatar=user.avatar,
            content=payload.content.strip(),
            rating=rating_record.rating if rating_record is not None else None,
        )
        self.comment_repo.save_comment(session, entity)
        if parent is not None:
            parent.reply_count = int(parent.reply_count or 0) + 1
            self.comment_repo.save_comment(session, parent)
        session.commit()
        return self._serialize_comments(
            session,
            [entity],
            current_user_id=user_id,
            material_uploader_id=material.uploader_id or 0,
        )[0]

    def update(self, session: Session, comment_id: int, payload: CommentUpdatePayload, *, user_id: int, can_moderate: bool) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_update_comment(session, comment_id, payload, user_id=user_id, can_moderate=can_moderate)
        self._bootstrap(session)
        entity = self.comment_repo.get_comment(session, comment_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if entity.user_id != user_id and not can_moderate:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权编辑该评论")
        entity.content = payload.content.strip()
        entity.edited = True
        self.comment_repo.save_comment(session, entity)
        session.commit()
        material = self._ensure_material(session, entity.material_id)
        return self._serialize_comments(
            session,
            [entity],
            current_user_id=user_id,
            material_uploader_id=material.uploader_id or 0,
        )[0]

    def delete(self, session: Session, comment_id: int, *, user_id: int, can_moderate: bool) -> None:
        if self.settings.requires_private_env_file:
            self._compat_delete_comment(session, comment_id, user_id=user_id, can_moderate=can_moderate)
            return
        self._bootstrap(session)
        entity = self.comment_repo.get_comment(session, comment_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if entity.user_id != user_id and not can_moderate:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除评论")
        entity.status = "deleted"
        entity.content = ""
        self.comment_repo.save_comment(session, entity)
        if entity.parent_id is not None:
            parent = self.comment_repo.get_comment(session, entity.parent_id)
            if parent is not None and int(parent.reply_count or 0) > 0:
                parent.reply_count = max(0, int(parent.reply_count or 0) - 1)
                self.comment_repo.save_comment(session, parent)
        session.commit()

    def like(self, session: Session, comment_id: int, user_id: int) -> int:
        if self.settings.requires_private_env_file:
            return self._compat_like_comment(session, comment_id, user_id)
        self._bootstrap(session)
        entity = self.comment_repo.get_comment(session, comment_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if self.comment_repo.find_like(session, comment_id, user_id) is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已点赞")
        self._require_user(session, user_id)
        self.comment_repo.add_like(session, comment_id=comment_id, user_id=user_id)
        next_like_count = int(entity.like_count or 0) + 1
        entity.like_count = next_like_count
        self.comment_repo.save_comment(session, entity)
        session.commit()
        return next_like_count

    def unlike(self, session: Session, comment_id: int, user_id: int) -> int:
        if self.settings.requires_private_env_file:
            return self._compat_unlike_comment(session, comment_id, user_id)
        self._bootstrap(session)
        entity = self.comment_repo.get_comment(session, comment_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        like = self.comment_repo.find_like(session, comment_id, user_id)
        if like is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="尚未点赞")
        self.comment_repo.remove_like(session, like)
        next_like_count = max(0, int(entity.like_count or 0) - 1)
        entity.like_count = next_like_count
        self.comment_repo.save_comment(session, entity)
        session.commit()
        return next_like_count

    def report(self, session: Session, comment_id: int, user_id: int, payload: CommentReportPayload) -> None:
        self._bootstrap(session)
        self.report_service.submit_report(session, reporter_id=user_id, target_type="COMMENT", target_id=comment_id, reason=payload.reason)

    def _compat_create_comment(self, session: Session, payload: CommentCreatePayload, user_id: int) -> dict[str, Any]:
        self._compat_ensure_material_exists(session, payload.materialId)
        self._require_user(session, user_id)
        parent = None
        if payload.parentId is not None:
            parent = self._compat_get_comment_base(session, payload.parentId)
            if parent is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标评论不存在")
            if int(parent["material_id"]) != int(payload.materialId):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="评论不属于当前资料")
        result = session.execute(
            text(
                """
                INSERT INTO comments (
                    material_id, user_id, parent_id, content, like_count, reply_count,
                    status, is_edited, created_at, updated_at
                )
                VALUES (
                    :material_id, :user_id, :parent_id, :content, 0, 0,
                    'visible', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "material_id": int(payload.materialId),
                "user_id": int(user_id),
                "parent_id": int(payload.parentId) if payload.parentId is not None else None,
                "content": payload.content.strip(),
            },
        )
        comment_id = int(result.lastrowid)
        if parent is not None:
            session.execute(
                text(
                    """
                    UPDATE comments
                    SET reply_count = COALESCE(reply_count, 0) + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :parent_id
                    """
                ),
                {"parent_id": int(parent["id"])},
            )
        row = self._compat_load_comment_row(session, comment_id)
        session.commit()
        return self._compat_to_comment_item(row, has_liked=False)

    def _compat_update_comment(
        self,
        session: Session,
        comment_id: int,
        payload: CommentUpdatePayload,
        *,
        user_id: int,
        can_moderate: bool,
    ) -> dict[str, Any]:
        row = self._compat_get_comment_base(session, comment_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if int(row["user_id"]) != int(user_id) and not can_moderate:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权编辑该评论")
        session.execute(
            text(
                """
                UPDATE comments
                SET content = :content,
                    is_edited = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :comment_id
                """
            ),
            {"comment_id": comment_id, "content": payload.content.strip()},
        )
        updated = self._compat_load_comment_row(session, comment_id)
        liked = self._compat_comment_liked(session, comment_id, user_id)
        session.commit()
        return self._compat_to_comment_item(updated, has_liked=liked)

    def _compat_delete_comment(self, session: Session, comment_id: int, *, user_id: int, can_moderate: bool) -> None:
        row = self._compat_get_comment_base(session, comment_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if int(row["user_id"]) != int(user_id) and not can_moderate:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除评论")
        session.execute(
            text(
                """
                UPDATE comments
                SET status = 'deleted',
                    content = '',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :comment_id
                """
            ),
            {"comment_id": comment_id},
        )
        if row["parent_id"] is not None:
            session.execute(
                text(
                    """
                    UPDATE comments
                    SET reply_count = CASE
                            WHEN COALESCE(reply_count, 0) > 0 THEN COALESCE(reply_count, 0) - 1
                            ELSE 0
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :parent_id
                    """
                ),
                {"parent_id": int(row["parent_id"])},
            )
        session.commit()

    def _compat_like_comment(self, session: Session, comment_id: int, user_id: int) -> int:
        row = self._compat_get_comment_base(session, comment_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if self._compat_comment_liked(session, comment_id, user_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已点赞")
        self._require_user(session, user_id)
        next_like_count = int(row["like_count"] or 0) + 1
        session.execute(
            text(
                """
                INSERT INTO comment_likes (comment_id, user_id, created_at)
                VALUES (:comment_id, :user_id, CURRENT_TIMESTAMP)
                """
            ),
            {"comment_id": comment_id, "user_id": user_id},
        )
        session.execute(
            text(
                """
                UPDATE comments
                SET like_count = :like_count,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :comment_id
                """
            ),
            {"comment_id": comment_id, "like_count": next_like_count},
        )
        session.commit()
        return next_like_count

    def _compat_unlike_comment(self, session: Session, comment_id: int, user_id: int) -> int:
        row = self._compat_get_comment_base(session, comment_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if not self._compat_comment_liked(session, comment_id, user_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="尚未点赞")
        next_like_count = max(0, int(row["like_count"] or 0) - 1)
        session.execute(
            text(
                """
                DELETE FROM comment_likes
                WHERE comment_id = :comment_id AND user_id = :user_id
                """
            ),
            {"comment_id": comment_id, "user_id": user_id},
        )
        session.execute(
            text(
                """
                UPDATE comments
                SET like_count = :like_count,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :comment_id
                """
            ),
            {"comment_id": comment_id, "like_count": next_like_count},
        )
        session.commit()
        return next_like_count

    def _compat_get_comment_base(self, session: Session, comment_id: int) -> dict[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT id, material_id, parent_id, user_id, like_count, reply_count, status
                FROM comments
                WHERE id = :comment_id
                LIMIT 1
                """
            ),
            {"comment_id": comment_id},
        ).mappings().first()
        return dict(row) if row is not None else None

    def _compat_comment_liked(self, session: Session, comment_id: int, user_id: int) -> bool:
        row = session.execute(
            text(
                """
                SELECT 1
                FROM comment_likes
                WHERE comment_id = :comment_id AND user_id = :user_id
                LIMIT 1
                """
            ),
            {"comment_id": comment_id, "user_id": user_id},
        ).first()
        return row is not None

    def _compat_load_comment_row(self, session: Session, comment_id: int) -> dict[str, Any]:
        row = session.execute(
            text(
                """
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
                WHERE c.id = :comment_id
                LIMIT 1
                """
            ),
            {"comment_id": comment_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        return dict(row)

    def _bootstrap(self, session: Session) -> None:
        seed = self.read_repo.load_seed()
        self.material_repo.ensure_seed_bootstrap(session, seed)
        self.comment_repo.ensure_seed_bootstrap(session, seed)

    def _ensure_material(self, session: Session, material_id: int):
        self._bootstrap(session)
        material = self.material_repo.get_material(session, material_id)
        if material is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        return material

    def _require_user(self, session: Session, user_id: int):
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    def _resolve_sort(self, sort: str):
        normalized = (sort or "latest").lower()
        if normalized == "hottest":
            return lambda item: (-(item.get("likeCount") or 0), -parse_iso_datetime(item.get("createdAt")).timestamp())
        return lambda item: -parse_iso_datetime(item.get("createdAt")).timestamp()

    def _serialize_comments(
        self,
        session: Session,
        entities: list[CommentRecord],
        *,
        current_user_id: int | None,
        material_uploader_id: int,
    ) -> list[dict[str, Any]]:
        if not entities:
            return []
        user_ids = [int(entity.user_id) for entity in entities if entity.user_id is not None]
        users_by_id = {int(user.id): user for user in self.auth_repo.find_users_by_ids(session, user_ids)}
        comment_ids = [int(entity.id) for entity in entities]
        liked_ids = self.comment_repo.liked_comment_ids(session, comment_ids=comment_ids, user_id=current_user_id)
        return [
            self._to_comment(entity, users_by_id.get(int(entity.user_id)), entity.id in liked_ids, material_uploader_id)
            for entity in entities
        ]

    def _to_comment(
        self,
        entity: CommentRecord,
        user,
        has_liked: bool,
        material_uploader_id: int,
    ) -> dict[str, Any]:
        nickname = entity.user_nickname or (user.nickname if user else None) or (user.username if user else "匿名同学")
        avatar = entity.user_avatar or (user.avatar if user else None)
        deleted = entity.status != "visible"
        return {
            "id": entity.id,
            "materialId": entity.material_id,
            "parentId": entity.parent_id,
            "content": "" if deleted else entity.content,
            "likeCount": int(entity.like_count or 0),
            "replyCount": int(entity.reply_count or 0),
            "edited": bool(entity.edited),
            "deleted": deleted,
            "createdAt": serialize_datetime(entity.created_at),
            "updatedAt": serialize_datetime(entity.updated_at),
            "user": {
                "id": entity.user_id,
                "nickname": nickname,
                "avatar": avatar,
                "isAuthor": material_uploader_id == entity.user_id,
            },
            "hasLiked": has_liked,
            "rating": entity.rating,
            "replies": [],
        }

    def _compat_list_comments(
        self,
        session: Session,
        material_id: int,
        *,
        sort: str,
        page: int,
        size: int,
        current_user_id: int | None,
    ) -> dict[str, Any]:
        self._compat_ensure_material_exists(session, material_id)
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
        rows = self._compat_load_comment_rows(
            session,
            material_id=material_id,
            parent_id=None,
            sort=sort,
            page=page,
            size=size,
        )
        liked_ids = self._compat_load_liked_ids(session, current_user_id, [int(row["id"]) for row in rows])
        items = [self._compat_to_comment_item(row, int(row["id"]) in liked_ids) for row in rows]
        _, meta = paginate_zero_based(list(range(total)), page=page, size=size)
        meta["total"] = total
        return {"items": items, "meta": meta}

    def _compat_list_replies(
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
        rows = self._compat_load_comment_rows(
            session,
            material_id=int(parent["material_id"]),
            parent_id=parent_id,
            sort="oldest",
            page=page,
            size=size,
        )
        liked_ids = self._compat_load_liked_ids(session, current_user_id, [int(row["id"]) for row in rows])
        items = [self._compat_to_comment_item(row, int(row["id"]) in liked_ids) for row in rows]
        _, meta = paginate_zero_based(list(range(total)), page=page, size=size)
        meta["total"] = total
        return {"items": items, "meta": meta}

    def _compat_ensure_material_exists(self, session: Session, material_id: int) -> None:
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

    async def _call_with_new_async_session(self, loader, *args, **kwargs):
        async with async_session_scope() as session:
            return await loader(session, *args, **kwargs)

    async def _compat_ensure_material_exists_async(self, session, material_id: int) -> None:
        exists = (
            await session.execute(
                text(
                    """
                    SELECT 1
                    FROM materials
                    WHERE id = :material_id
                    LIMIT 1
                    """
                ),
                {"material_id": material_id},
            )
        ).scalar()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

    async def _compat_load_comment_parent_async(self, session, parent_id: int) -> dict[str, Any]:
        parent = (
            await session.execute(
                text(
                    """
                    SELECT id, material_id
                    FROM comments
                    WHERE id = :parent_id
                    LIMIT 1
                    """
                ),
                {"parent_id": parent_id},
            )
        ).mappings().first()
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        return dict(parent)

    async def _compat_count_comments_async(self, session, *, material_id: int | None, parent_id: int | None) -> int:
        if parent_id is None:
            total = (
                await session.execute(
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
                )
            ).scalar()
            return int(total or 0)
        total = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM comments
                    WHERE parent_id = :parent_id
                      AND status = 'visible'
                    """
                ),
                {"parent_id": parent_id},
            )
        ).scalar()
        return int(total or 0)

    def _compat_load_comment_rows(
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

    async def _compat_load_comment_rows_async(
        self,
        session,
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
        rows = (
            await session.execute(
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
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    def _compat_load_liked_ids(self, session: Session, current_user_id: int | None, comment_ids: list[int]) -> set[int]:
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

    async def _compat_load_liked_ids_async(self, session, current_user_id: int | None, comment_ids: list[int]) -> set[int]:
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
        rows = (await session.execute(stmt, {"user_id": current_user_id, "comment_ids": comment_ids})).scalars().all()
        return {int(value) for value in rows}

    def _compat_to_comment_item(self, row: dict[str, Any], has_liked: bool) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "materialId": int(row["material_id"]),
            "parentId": int(row["parent_id"]) if row["parent_id"] is not None else None,
            "content": row["content"] or "",
            "likeCount": int(row["like_count"] or 0),
            "replyCount": int(row["reply_count"] or 0),
            "edited": bool(row["is_edited"]),
            "deleted": str(row.get("status") or "").lower() != "visible",
            "createdAt": self._compat_serialize_datetime(row["created_at"]),
            "updatedAt": self._compat_serialize_datetime(row["updated_at"]),
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

    def _compat_serialize_datetime(self, value: Any) -> str | None:
        return compat_serialize_datetime(value)
