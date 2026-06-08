from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.community import ReportRecord
from app.repos.community_repo import CommunityRepository
from app.services.report_service import ReportService


class _DummyReadRepo:
    def load_seed(self):
        return {}


class _DummySeedRepo:
    def ensure_seed_bootstrap(self, session: Session, seed: dict) -> None:
        del session, seed


class _DummyAuthRepo:
    def __init__(self) -> None:
        self.saved_users = []

    def find_user_by_id(self, session: Session, user_id: int):
        del session
        return SimpleNamespace(id=user_id, username=f"user-{user_id}", nickname=f"User {user_id}", status="active")

    def save_user(self, session: Session, user) -> None:
        del session
        self.saved_users.append(user)


class _NoFullListCommunityRepo(CommunityRepository):
    def list_reports(self, session: Session):
        del session
        raise AssertionError("admin report list should not load all reports")


def _service(auth_repo: _DummyAuthRepo | None = None) -> ReportService:
    seed_repo = _DummySeedRepo()
    return ReportService(
        read_repo=_DummyReadRepo(),  # type: ignore[arg-type]
        auth_repo=auth_repo or _DummyAuthRepo(),  # type: ignore[arg-type]
        material_repo=seed_repo,  # type: ignore[arg-type]
        comment_repo=seed_repo,  # type: ignore[arg-type]
        market_repo=seed_repo,  # type: ignore[arg-type]
        community_repo=_NoFullListCommunityRepo(),
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    ReportRecord.__table__.create(bind=engine)
    return Session(engine)


def _add_report(
    session: Session,
    *,
    report_id: int,
    status: str,
    target_type: str = "USER",
    target_id: int,
    reporter_id: int = 1,
    created_at: datetime,
) -> None:
    session.add(
        ReportRecord(
            id=report_id,
            target_type=target_type,
            target_id=target_id,
            reporter_id=reporter_id,
            reason="疑似违规",
            status=status,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def test_admin_report_list_filters_before_pagination_without_loading_all_reports() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        for index in range(5):
            _add_report(
                session,
                report_id=100 + index,
                status="RESOLVED",
                target_id=200 + index,
                created_at=base + timedelta(minutes=index),
            )
        _add_report(session, report_id=10, status="PENDING", target_id=50, created_at=base - timedelta(days=1))
        _add_report(session, report_id=9, status="PENDING", target_id=51, created_at=base - timedelta(days=2))
        session.commit()

        data = service.list_for_admin(session, page=0, size=1, status_value=" pending ", target_type=" user ")

    assert data["meta"] == {"page": 0, "size": 1, "total": 2}
    assert [item["id"] for item in data["items"]] == [10]
    assert data["items"][0]["targetLabel"] == "User 50"


def test_admin_report_list_combines_status_and_target_type_filters() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_report(session, report_id=1, status="PENDING", target_type="USER", target_id=50, created_at=base)
        _add_report(
            session,
            report_id=2,
            status="PENDING",
            target_type="MARKET_ITEM",
            target_id=201,
            created_at=base + timedelta(minutes=1),
        )
        _add_report(
            session,
            report_id=3,
            status="RESOLVED",
            target_type="MARKET_ITEM",
            target_id=202,
            created_at=base + timedelta(minutes=2),
        )
        session.commit()

        data = service.list_for_admin(session, page=0, size=20, status_value="pending", target_type="user")

    assert data["meta"] == {"page": 0, "size": 20, "total": 1}
    assert [item["id"] for item in data["items"]] == [1]


def test_submit_report_counts_active_reports_without_loading_all_reports() -> None:
    auth_repo = _DummyAuthRepo()
    service = _service(auth_repo=auth_repo)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_report(session, report_id=1, status="PENDING", target_id=99, reporter_id=4, created_at=base)
        _add_report(session, report_id=2, status="PENDING", target_id=99, reporter_id=5, created_at=base)
        session.commit()

        entity = service.submit_report(
            session,
            reporter_id=6,
            target_type="user",
            target_id=99,
            reason="第三次举报",
        )
        created_report = (entity.target_type, entity.target_id, entity.reporter_id)

    assert created_report == ("USER", 99, 6)
    assert [(user.id, user.status) for user in auth_repo.saved_users] == [(99, "hidden")]
