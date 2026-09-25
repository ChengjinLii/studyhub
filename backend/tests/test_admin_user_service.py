from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.models.auth import AuthUser
from app.services.admin_user_service import AdminUserService
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


class _DummyReadRepo:
    def __init__(self, seed=None):
        self.seed = seed or {}
        self.loads = 0

    def load_seed(self):
        self.loads += 1
        return self.seed


def _service(read_repo: _DummyReadRepo | None = None) -> AdminUserService:
    return AdminUserService(read_repo or _DummyReadRepo(), admin_repo=None, auth_repo=None, auth_service=None)  # type: ignore[arg-type]


def _add_user(session: Session, *, username: str, nickname: str, created_at: datetime) -> None:
    session.add(
        AuthUser(
            username=username,
            nickname=nickname,
            password_hash="hash",
            verified=True,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    AuthUser.__table__.create(bind=engine)
    return Session(engine)


def test_admin_user_list_filters_before_applying_limit() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        for index in range(205):
            _add_user(
                session,
                username=f"recent-{index}",
                nickname=f"Recent {index}",
                created_at=base + timedelta(minutes=index),
            )
        _add_user(session, username="target-alice", nickname="Target Alice", created_at=base - timedelta(days=1))
        _add_user(session, username="target-bob", nickname="Target Bob", created_at=base - timedelta(days=2))
        session.commit()

        users = service.list_users(session, keyword="target")

    assert [user["username"] for user in users] == ["target-alice", "target-bob"]


def test_admin_user_list_treats_like_wildcards_as_literal_keyword_text() -> None:
    service = _service()
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_user(session, username="plain", nickname="Plain", created_at=created_at)
        _add_user(session, username="percent%user", nickname="Percent", created_at=created_at + timedelta(minutes=1))
        _add_user(session, username="under_score", nickname="Under", created_at=created_at + timedelta(minutes=2))
        session.commit()

        percent_users = service.list_users(session, keyword="%")
        underscore_users = service.list_users(session, keyword="_")

    assert [user["username"] for user in percent_users] == ["percent%user"]
    assert [user["username"] for user in underscore_users] == ["under_score"]


def test_admin_user_list_reuses_seed_for_summaries() -> None:
    read_repo = _DummyReadRepo(
        {
            "profileSummary": {
                "1": {"totals": {"totalEarnings": 12.5}},
                "2": {"totals": {"totalEarnings": 30}},
            }
        }
    )
    service = _service(read_repo)
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_user(session, username="alice", nickname="Alice", created_at=created_at)
        _add_user(session, username="bob", nickname="Bob", created_at=created_at + timedelta(minutes=1))
        session.commit()

        users = service.list_users(session, keyword=None)

    assert read_repo.loads == 1
    assert [user["totalEarnings"] for user in users] == [30.0, 12.5]


def _set_role_mask(user_id: int, role_mask: int) -> None:
    with session_scope() as session:
        user = session.get(AuthUser, user_id)
        assert user is not None
        user.role_mask = role_mask


def _role_mask(user_id: int) -> int | None:
    with session_scope() as session:
        user = session.get(AuthUser, user_id)
        assert user is not None
        return user.role_mask


def test_admin_cannot_strip_developer_role(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)
    _set_role_mask(2, 24)

    response = client.patch("/api/admin/users?id=2", headers=build_auth_headers(3, 8), json={"roleMask": 8})
    path_response = client.patch("/api/admin/users/2/roles", headers=build_auth_headers(3, 8), json={"roleMask": 1})

    assert response.status_code == 403
    assert path_response.status_code == 403
    assert _role_mask(2) == 24


def test_developer_can_change_developer_roles(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)
    _set_role_mask(2, 24)
    _set_role_mask(3, 24)

    response = client.patch("/api/admin/users?id=2", headers=build_auth_headers(3, 24), json={"roleMask": 8})

    assert response.status_code == 200
    assert _role_mask(2) == 8
