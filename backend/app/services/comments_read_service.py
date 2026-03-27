from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.repos.read_api_repo import ReadApiRepository
from app.services.read_support import paginate_zero_based, parse_iso_datetime


class CommentsReadService:
    def __init__(self, repo: ReadApiRepository) -> None:
        self.repo = repo

    def list_comments(self, material_id: int, *, sort: str, page: int, size: int, current_user_id: int | None) -> dict[str, Any]:
        seed = self.repo.load_seed()
        if not any(int(item["id"]) == material_id for item in seed.get("materials", [])):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        comments = [
            self._to_comment(item, current_user_id, include_replies=False)
            for item in seed.get("comments", [])
            if int(item.get("materialId", 0)) == material_id and item.get("parentId") is None and item.get("status", "visible") == "visible"
        ]
        comments.sort(key=self._resolve_sort(sort))
        items, meta = paginate_zero_based(comments, page=page, size=size)
        return {"items": items, "meta": meta}

    def list_replies(self, parent_id: int, *, page: int, size: int, current_user_id: int | None) -> dict[str, Any]:
        seed = self.repo.load_seed()
        parent = next((item for item in seed.get("comments", []) if int(item["id"]) == parent_id), None)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
        replies = [
            self._to_comment(item, current_user_id, include_replies=False)
            for item in seed.get("comments", [])
            if int(item.get("parentId") or 0) == parent_id and item.get("status", "visible") == "visible"
        ]
        replies.sort(key=lambda item: parse_iso_datetime(item.get("createdAt")))
        items, meta = paginate_zero_based(replies, page=page, size=size)
        return {"items": items, "meta": meta}

    def _resolve_sort(self, sort: str):
        normalized = (sort or "latest").lower()
        if normalized == "hottest":
            return lambda item: (-(item.get("likeCount") or 0), -parse_iso_datetime(item.get("createdAt")).timestamp())
        return lambda item: -parse_iso_datetime(item.get("createdAt")).timestamp()

    def _to_comment(self, item: dict[str, Any], current_user_id: int | None, *, include_replies: bool) -> dict[str, Any]:
        seed = self.repo.load_seed()
        relationships = seed.get("relationships") or {}
        likes = (relationships.get("commentLikes") or {}).get(str(current_user_id), []) if current_user_id is not None else []
        material = next((entry for entry in seed.get("materials", []) if int(entry["id"]) == int(item["materialId"])), None)
        return {
            "id": item["id"],
            "materialId": item["materialId"],
            "parentId": item.get("parentId"),
            "content": item.get("content", ""),
            "likeCount": int(item.get("likeCount", 0)),
            "replyCount": int(item.get("replyCount", 0)),
            "edited": bool(item.get("edited")),
            "deleted": item.get("status", "visible") != "visible",
            "createdAt": item.get("createdAt"),
            "updatedAt": item.get("updatedAt"),
            "user": {
                "id": item.get("userId"),
                "nickname": item.get("nickname"),
                "avatar": item.get("avatar"),
                "isAuthor": material is not None and int(material.get("uploaderId", 0)) == int(item.get("userId", 0)),
            },
            "hasLiked": int(item["id"]) in {int(value) for value in likes},
            "rating": item.get("rating"),
            "replies": [] if include_replies else [],
        }
