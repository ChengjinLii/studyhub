from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.community import NotificationRecord
from app.repos.community_repo import CommunityRepository
from app.services.notification_service import NotificationService


class _DummyAuthRepo:
    def __init__(self, users_by_id: dict[int, object] | None = None) -> None:
        self.users_by_id = users_by_id or {}
        self.bulk_queries: list[list[int]] = []

    def find_user_by_id(self, session: Session, user_id: int):
        del session
        return self.users_by_id.get(user_id) or SimpleNamespace(
            id=user_id,
            username=f"user-{user_id}",
            nickname=f"User {user_id}",
            notification_read_at=None,
            market_event_read_at=None,
        )

    def find_users_by_ids(self, session: Session, user_ids: list[int]):
        del session
        normalized = sorted(set(user_ids))
        self.bulk_queries.append(normalized)
        return [self.users_by_id[user_id] for user_id in normalized if user_id in self.users_by_id]


class _DummyMarketRepo:
    def __init__(self, wants=None, items_by_id: dict[int, object] | None = None) -> None:
        self.wants = wants or []
        self.items_by_id = items_by_id or {}
        self.seller_queries: list[tuple[int, int | None]] = []
        self.item_queries: list[list[int]] = []

    def wants_for_seller(self, session: Session, seller_id: int, *, limit: int | None = None):
        del session
        self.seller_queries.append((seller_id, limit))
        return self.wants[:limit] if limit is not None else list(self.wants)

    def list_items_by_ids(self, session: Session, item_ids: list[int]):
        del session
        normalized = sorted(set(item_ids))
        self.item_queries.append(normalized)
        return [self.items_by_id[item_id] for item_id in normalized if item_id in self.items_by_id]


class _TrackingCommunityRepo(CommunityRepository):
    def __init__(self) -> None:
        self.visible_queries: list[tuple[int, int | None]] = []

    def list_notifications(self, session: Session):
        del session
        raise AssertionError("notification reads should not load all notifications")

    def list_notifications_for_user(self, session: Session, user_id: int, *, limit: int | None = None):
        self.visible_queries.append((user_id, limit))
        return super().list_notifications_for_user(session, user_id, limit=limit)


def _service(
    repo: _TrackingCommunityRepo,
    market_repo: _DummyMarketRepo | None = None,
    auth_repo: _DummyAuthRepo | None = None,
) -> NotificationService:
    return NotificationService(auth_repo or _DummyAuthRepo(), repo, market_repo or _DummyMarketRepo())  # type: ignore[arg-type]


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    NotificationRecord.__table__.create(bind=engine)
    return Session(engine)


def _add_notification(
    session: Session,
    *,
    notification_id: int,
    user_id: int | None,
    message: str,
    created_at: datetime,
    admin_user_id: int | None = None,
) -> None:
    session.add(
        NotificationRecord(
            id=notification_id,
            admin_user_id=admin_user_id,
            user_id=user_id,
            message=message,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def test_notification_list_filters_in_query_without_loading_all_notifications() -> None:
    repo = _TrackingCommunityRepo()
    market_repo = _DummyMarketRepo()
    service = _service(repo, market_repo)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        for index in range(60):
            _add_notification(
                session,
                notification_id=100 + index,
                user_id=2,
                message=f"other-{index}",
                created_at=base + timedelta(minutes=index),
            )
        _add_notification(session, notification_id=1, user_id=1, message="direct", created_at=base - timedelta(minutes=1))
        _add_notification(session, notification_id=2, user_id=None, message="broadcast", created_at=base - timedelta(minutes=2))
        session.commit()

        items = service.list_recent(session, user_id=1)

    assert repo.visible_queries == [(1, 50)]
    assert market_repo.seller_queries == [(1, 50)]
    assert [item["message"] for item in items] == ["direct", "broadcast"]


def test_notification_summary_queries_only_latest_visible_notification() -> None:
    repo = _TrackingCommunityRepo()
    market_repo = _DummyMarketRepo()
    service = _service(repo, market_repo)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_notification(session, notification_id=1, user_id=1, message="older", created_at=base)
        _add_notification(session, notification_id=2, user_id=None, message="newer", created_at=base + timedelta(minutes=1))
        session.commit()

        summary = service.get_summary(session, user_id=1)

    assert repo.visible_queries == [(1, 1)]
    assert market_repo.seller_queries == [(1, 1)]
    assert summary["hasUnread"] is True
    assert summary["latestMessage"] == "newer"


def test_notification_list_batches_sender_and_market_item_details() -> None:
    repo = _TrackingCommunityRepo()
    auth_repo = _DummyAuthRepo(
        {
            10: SimpleNamespace(id=10, username="admin-a", nickname="管理员A"),
        }
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    market_repo = _DummyMarketRepo(
        wants=[
            SimpleNamespace(id=5, item_id=301, created_at=base + timedelta(minutes=1)),
            SimpleNamespace(id=6, item_id=302, created_at=base),
        ],
        items_by_id={
            301: SimpleNamespace(id=301, title="计算器", want_count=3),
            302: SimpleNamespace(id=302, title="教材", want_count=1),
        },
    )
    service = _service(repo, market_repo, auth_repo)
    with _session() as session:
        _add_notification(
            session,
            notification_id=1,
            user_id=1,
            message="direct",
            admin_user_id=10,
            created_at=base + timedelta(minutes=3),
        )
        _add_notification(
            session,
            notification_id=2,
            user_id=None,
            message="broadcast",
            admin_user_id=11,
            created_at=base + timedelta(minutes=2),
        )
        session.commit()

        items = service.list_recent(session, user_id=1)

    assert auth_repo.bulk_queries == [[10, 11]]
    assert market_repo.item_queries == [[301, 302]]
    assert [(item["message"], item["sender"]) for item in items] == [
        ("direct", "管理员A"),
        ("broadcast", "管理员"),
        ("你的好物「计算器」有 3 人想要", "想要提醒"),
        ("你的好物「教材」有 1 人想要", "想要提醒"),
    ]
