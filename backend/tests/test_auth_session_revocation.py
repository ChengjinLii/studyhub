from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_auth_repo, get_token_codec
from app.core.db import session_scope
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


def test_session_version_revokes_existing_token(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)
    old_headers = build_auth_headers(1, 1)
    with session_scope() as session:
        user = get_auth_repo().find_user_by_id(session, 1)
        assert user is not None
        assert user.status == "active"
        assert get_auth_repo().get_session_version(session, 1) == 0
    assert client.get("/api/me/account", headers=old_headers).status_code == 200

    with session_scope() as session:
        version = get_auth_repo().bump_session_version(session, 1, reason="test_revocation")
    assert version == 1
    assert client.get("/api/me/account", headers=old_headers).status_code == 401

    new_token = get_token_codec().encode(
        {"sub": "1", "roleMask": 1, "sessionVersion": version},
        ttl_seconds=3600,
    )
    assert client.get("/api/me/account", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_inactive_account_cannot_reuse_existing_token(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(1, 1)
    with session_scope() as session:
        user = get_auth_repo().find_user_by_id(session, 1)
        assert user is not None
        assert user.status == "active"
    assert client.get("/api/me/account", headers=headers).status_code == 200

    with session_scope() as session:
        user = get_auth_repo().find_user_by_id(session, 1)
        assert user is not None
        user.status = "hidden"
        get_auth_repo().save_user(session, user)

    assert client.get("/api/me/account", headers=headers).status_code == 401
