from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.community import NotificationRecord
from app.repos.community_repo import CommunityRepository
from app.services.notification_service import NotificationService


class _DummyAuthRepo:
    def find_user_by_id(self, session: Session, user_id: int):
        del session
        return SimpleNamespace(
            id=user_id,
            username=f"user-{user_id}",
            nickname=f"User {user_id}",
            notification_read_at=None,
            market_event_read_at=None,
        )


class _DummyMarketRepo:
    def wants_for_seller(self, session: Session, seller_id: int):
        del session, seller_id
        return []


class _TrackingCommunityRepo(CommunityRepository):
    def __init__(self) -> None:
        self.visible_queries: list[tuple[int, int | None]] = []

    def list_notifications(self, session: Session):
        del session
        raise AssertionError("notification reads should not load all notifications")

    def list_notifications_for_user(self, session: Session, user_id: int, *, limit: int | None = None):
        self.visible_queries.append((user_id, limit))
        return super().list_notifications_for_user(session, user_id, limit=limit)


def _service(repo: _TrackingCommunityRepo) -> NotificationService:
    return NotificationService(_DummyAuthRepo(), repo, _DummyMarketRepo())  # type: ignore[arg-type]


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
) -> None:
    session.add(
        NotificationRecord(
            id=notification_id,
            admin_user_id=None,
            user_id=user_id,
            message=message,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def test_notification_list_filters_in_query_without_loading_all_notifications() -> None:
    repo = _TrackingCommunityRepo()
    service = _service(repo)
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
    assert [item["message"] for item in items] == ["direct", "broadcast"]


def test_notification_summary_queries_only_latest_visible_notification() -> None:
    repo = _TrackingCommunityRepo()
    service = _service(repo)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_notification(session, notification_id=1, user_id=1, message="older", created_at=base)
        _add_notification(session, notification_id=2, user_id=None, message="newer", created_at=base + timedelta(minutes=1))
        session.commit()

        summary = service.get_summary(session, user_id=1)

    assert repo.visible_queries == [(1, 1)]
    assert summary["hasUnread"] is True
    assert summary["latestMessage"] == "newer"
