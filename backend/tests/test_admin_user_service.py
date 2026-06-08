from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.auth import AuthUser
from app.services.admin_user_service import AdminUserService


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
