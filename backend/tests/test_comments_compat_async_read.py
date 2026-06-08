from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services.comments_service import CommentsService


def _build_service() -> CommentsService:
    fake_settings = SimpleNamespace(
        requires_private_env_file=True,
        async_read_db_enabled=True,
    )
    return CommentsService(fake_settings, read_repo=None, auth_repo=None, material_repo=None, comment_repo=None, report_service=None)


def _comment_row(comment_id: int, *, parent_id: int | None = None) -> dict[str, object]:
    return {
        "id": comment_id,
        "material_id": 101,
        "parent_id": parent_id,
        "user_id": 2,
        "content": "复习建议很有用",
        "like_count": 4,
        "reply_count": 1,
        "status": "visible",
        "is_edited": 1,
        "created_at": "2026-01-02T03:04:05Z",
        "updated_at": "2026-01-03T03:04:05Z",
        "user_nickname": "白山",
        "user_username": "baishan",
        "user_avatar": "/avatar.png",
        "uploader_id": 2,
        "rating": 5,
    }


def test_async_legacy_comment_list_keeps_meta_liked_and_author_state(monkeypatch) -> None:
    service = _build_service()
    row = _comment_row(9001)

    async def fake_call(loader, *args, **kwargs):
        name = loader.__name__
        if name == "_compat_ensure_material_exists_async":
            assert args == (101,)
            return None
        if name == "_compat_count_comments_async":
            assert kwargs == {"material_id": 101, "parent_id": None}
            return 8
        if name == "_compat_load_comment_rows_async":
            assert kwargs == {"material_id": 101, "parent_id": None, "sort": "hottest", "page": 1, "size": 5}
            return [row]
        if name == "_compat_load_liked_ids_async":
            assert args == (12, [9001])
            return {9001}
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.list_comments_async(None, 101, sort="hottest", page=1, size=5, current_user_id=12))

    assert data["meta"] == {"page": 1, "size": 5, "total": 8}
    assert data["items"][0]["id"] == 9001
    assert data["items"][0]["hasLiked"] is True
    assert data["items"][0]["user"]["isAuthor"] is True
    assert data["items"][0]["rating"] == 5


def test_async_legacy_comment_replies_keep_meta_and_liked_state(monkeypatch) -> None:
    service = _build_service()
    row = _comment_row(9002, parent_id=9001)

    async def fake_call(loader, *args, **kwargs):
        name = loader.__name__
        if name == "_compat_load_comment_parent_async":
            assert args == (9001,)
            return {"id": 9001, "material_id": 101}
        if name == "_compat_count_comments_async":
            assert kwargs == {"material_id": None, "parent_id": 9001}
            return 2
        if name == "_compat_load_comment_rows_async":
            assert kwargs == {"material_id": 101, "parent_id": 9001, "sort": "oldest", "page": 0, "size": 20}
            return [row]
        if name == "_compat_load_liked_ids_async":
            assert args == (12, [9002])
            return set()
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.list_replies_async(None, 9001, page=0, size=20, current_user_id=12))

    assert data["meta"] == {"page": 0, "size": 20, "total": 2}
    assert data["items"][0]["id"] == 9002
    assert data["items"][0]["parentId"] == 9001
    assert data["items"][0]["hasLiked"] is False
