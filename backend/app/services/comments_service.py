from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.comments import CommentRecord
from app.repos.auth_repo import AuthRepository
from app.repos.comment_repo import CommentRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.comments import CommentCreatePayload, CommentReportPayload, CommentUpdatePayload
from app.services.read_support import paginate_zero_based, parse_iso_datetime, serialize_datetime


class CommentsService:
    def __init__(
        self,
        read_repo: ReadApiRepository,
        auth_repo: AuthRepository,
        material_repo: MaterialRepository,
        comment_repo: CommentRepository,
        report_service,
    ) -> None:
        self.read_repo = read_repo
        self.auth_repo = auth_repo
        self.material_repo = material_repo
        self.comment_repo = comment_repo
        self.report_service = report_service

    def list_comments(self, session: Session, material_id: int, *, sort: str, page: int, size: int, current_user_id: int | None) -> dict[str, Any]:
        material = self._ensure_material(session, material_id)
        comments = [self._to_comment(session, item, current_user_id, material.uploader_id or 0) for item in self.comment_repo.list_comments(session, material_id=material_id, parent_id=None, visible_only=True)]
        comments.sort(key=self._resolve_sort(sort))
        items, meta = paginate_zero_based(comments, page=page, size=size)
        return {"items": items, "meta": meta}

    def list_replies(self, session: Session, parent_id: int, *, page: int, size: int, current_user_id: int | None) -> dict[str, Any]:
        self._bootstrap(session)
        parent = self.comment_repo.get_comment(session, parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        material = self._ensure_material(session, parent.material_id)
        replies = [self._to_comment(session, item, current_user_id, material.uploader_id or 0) for item in self.comment_repo.list_comments(session, material_id=parent.material_id, parent_id=parent_id, visible_only=True)]
        replies.sort(key=lambda item: parse_iso_datetime(item.get("createdAt")))
        items, meta = paginate_zero_based(replies, page=page, size=size)
        return {"items": items, "meta": meta}

    def create(self, session: Session, payload: CommentCreatePayload, user_id: int) -> dict[str, Any]:
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
        return self._to_comment(session, entity, user_id, material.uploader_id or 0)

    def update(self, session: Session, comment_id: int, payload: CommentUpdatePayload, *, user_id: int, can_moderate: bool) -> dict[str, Any]:
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
        return self._to_comment(session, entity, user_id, material.uploader_id or 0)

    def delete(self, session: Session, comment_id: int, *, user_id: int, can_moderate: bool) -> None:
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
        self._bootstrap(session)
        entity = self.comment_repo.get_comment(session, comment_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        if self.comment_repo.find_like(session, comment_id, user_id) is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已点赞")
        self._require_user(session, user_id)
        self.comment_repo.add_like(session, comment_id=comment_id, user_id=user_id)
        entity.like_count = int(entity.like_count or 0) + 1
        self.comment_repo.save_comment(session, entity)
        session.commit()
        return int(entity.like_count or 0)

    def unlike(self, session: Session, comment_id: int, user_id: int) -> int:
        self._bootstrap(session)
        entity = self.comment_repo.get_comment(session, comment_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        like = self.comment_repo.find_like(session, comment_id, user_id)
        if like is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="尚未点赞")
        self.comment_repo.remove_like(session, like)
        entity.like_count = max(0, int(entity.like_count or 0) - 1)
        self.comment_repo.save_comment(session, entity)
        session.commit()
        return int(entity.like_count or 0)

    def report(self, session: Session, comment_id: int, user_id: int, payload: CommentReportPayload) -> None:
        self._bootstrap(session)
        self.report_service.submit_report(session, reporter_id=user_id, target_type="COMMENT", target_id=comment_id, reason=payload.reason)

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

    def _to_comment(self, session: Session, entity: CommentRecord, current_user_id: int | None, material_uploader_id: int) -> dict[str, Any]:
        user = self.auth_repo.find_user_by_id(session, entity.user_id)
        liked_ids = self.comment_repo.liked_comment_ids(session, comment_ids=[entity.id], user_id=current_user_id)
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
            "hasLiked": entity.id in liked_ids,
            "rating": entity.rating,
            "replies": [],
        }
