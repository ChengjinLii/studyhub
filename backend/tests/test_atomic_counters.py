from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_comments_service, get_materials_service
from app.core.db import session_scope
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


MATERIAL_ID = 101
ADMIN_USER_ID = 3
CONCURRENT_BUMP = 5


def _concurrent_bump(table: str, column: str, row_id: int) -> None:
    """Simulate another request committing an increment while ours is in flight."""
    with session_scope() as other:
        other.execute(
            text(f"UPDATE {table} SET {column} = {column} + :delta WHERE id = :row_id"),
            {"delta": CONCURRENT_BUMP, "row_id": row_id},
        )


def _bump_before(monkeypatch: pytest.MonkeyPatch, repo: object, method: str, table: str, column: str, row_id: int) -> None:
    original = getattr(repo, method)

    def wrapper(*args, **kwargs):
        _concurrent_bump(table, column, row_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, method, wrapper)


def _column(table: str, column: str, row_id: int) -> int:
    with session_scope() as session:
        return int(session.execute(text(f"SELECT {column} FROM {table} WHERE id = :id"), {"id": row_id}).scalar_one())


def _bootstrap_materials(auth_service: AuthService):
    seed_read_users(auth_service)
    service = get_materials_service()
    with session_scope() as session:
        service._bootstrap(session)
    return service


def test_material_like_and_unlike_do_not_lose_concurrent_updates(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    service = _bootstrap_materials(auth_service)
    base = _column("materials", "like_count", MATERIAL_ID)
    _bump_before(monkeypatch, service.material_repo, "add_like", "materials", "like_count", MATERIAL_ID)
    _bump_before(monkeypatch, service.material_repo, "remove_like", "materials", "like_count", MATERIAL_ID)

    with session_scope() as session:
        liked = service.like(session, MATERIAL_ID, ADMIN_USER_ID)
    assert liked == base + CONCURRENT_BUMP + 1
    assert _column("materials", "like_count", MATERIAL_ID) == liked

    with session_scope() as session:
        unliked = service.unlike(session, MATERIAL_ID, ADMIN_USER_ID)
    assert unliked == liked + CONCURRENT_BUMP - 1
    assert _column("materials", "like_count", MATERIAL_ID) == unliked


def test_material_rating_does_not_lose_concurrent_updates(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    service = _bootstrap_materials(auth_service)
    base = _column("materials", "rating_count", MATERIAL_ID)
    _bump_before(monkeypatch, service.material_repo, "save_rating", "materials", "rating_count", MATERIAL_ID)

    with session_scope() as session:
        rated = service.rate_material(session, MATERIAL_ID, ADMIN_USER_ID, 5)

    assert rated["ratingCount"] == base + CONCURRENT_BUMP + 1
    assert _column("materials", "rating_count", MATERIAL_ID) == rated["ratingCount"]


def test_material_view_does_not_lose_concurrent_updates(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    service = _bootstrap_materials(auth_service)
    base = _column("materials", "view_count", MATERIAL_ID)
    _bump_before(monkeypatch, service.material_repo, "add_view", "materials", "view_count", MATERIAL_ID)

    with session_scope() as session:
        viewed = service.record_view(session, MATERIAL_ID, ADMIN_USER_ID, True, "viewer-atomic")

    assert viewed == base + CONCURRENT_BUMP + 1
    assert _column("materials", "view_count", MATERIAL_ID) == viewed


def test_comment_like_and_unlike_do_not_lose_concurrent_updates(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_read_users(auth_service)
    created = client.post(
        "/api/comments",
        headers=build_auth_headers(1, 1),
        json={"materialId": MATERIAL_ID, "content": "atomic counter comment"},
    )
    assert created.status_code == 200
    comment_id = int(created.json()["data"]["id"])
    service = get_comments_service()
    _bump_before(monkeypatch, service.comment_repo, "add_like", "comments", "like_count", comment_id)
    _bump_before(monkeypatch, service.comment_repo, "remove_like", "comments", "like_count", comment_id)

    with session_scope() as session:
        liked = service.like(session, comment_id, 2)
    assert liked == CONCURRENT_BUMP + 1
    assert _column("comments", "like_count", comment_id) == liked

    with session_scope() as session:
        unliked = service.unlike(session, comment_id, 2)
    assert unliked == 2 * CONCURRENT_BUMP
    assert _column("comments", "like_count", comment_id) == unliked
