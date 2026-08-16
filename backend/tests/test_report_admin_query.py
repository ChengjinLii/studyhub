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
        self.revoked_user_ids: list[int] = []

    def find_user_by_id(self, session: Session, user_id: int):
        del session
        return SimpleNamespace(id=user_id, username=f"user-{user_id}", nickname=f"User {user_id}", status="active")

    def save_user(self, session: Session, user) -> None:
        del session
        self.saved_users.append(user)

    def bump_session_version(self, session: Session, user_id: int, *, reason: str) -> int:
        del session, reason
        self.revoked_user_ids.append(user_id)
        return 1


class _BulkAuthRepo(_DummyAuthRepo):
    def __init__(self, users_by_id: dict[int, object]) -> None:
        super().__init__()
        self.users_by_id = users_by_id
        self.bulk_queries: list[list[int]] = []
        self.single_queries: list[int] = []

    def find_user_by_id(self, session: Session, user_id: int):
        del session
        self.single_queries.append(user_id)
        return self.users_by_id.get(user_id)

    def find_users_by_ids(self, session: Session, user_ids: list[int]):
        del session
        normalized = sorted(set(user_ids))
        self.bulk_queries.append(normalized)
        return [self.users_by_id[user_id] for user_id in normalized if user_id in self.users_by_id]


class _BulkTargetRepo:
    def __init__(self, records_by_id: dict[int, object], method_name: str) -> None:
        self.records_by_id = records_by_id
        self.method_name = method_name
        self.bulk_queries: list[list[int]] = []

    def ensure_seed_bootstrap(self, session: Session, seed: dict) -> None:
        del session, seed

    def __getattr__(self, name: str):
        if name != self.method_name:
            raise AttributeError(name)

        def load(session: Session, record_ids: list[int]):
            del session
            normalized = sorted(set(record_ids))
            self.bulk_queries.append(normalized)
            return [self.records_by_id[record_id] for record_id in normalized if record_id in self.records_by_id]

        return load


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


def _service_with_targets(
    *,
    auth_repo,
    material_repo,
    comment_repo,
    market_repo,
) -> ReportService:
    return ReportService(
        read_repo=_DummyReadRepo(),  # type: ignore[arg-type]
        auth_repo=auth_repo,  # type: ignore[arg-type]
        material_repo=material_repo,  # type: ignore[arg-type]
        comment_repo=comment_repo,  # type: ignore[arg-type]
        market_repo=market_repo,  # type: ignore[arg-type]
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
    assert auth_repo.revoked_user_ids == [99]


def test_admin_report_list_batches_reporters_and_target_info() -> None:
    auth_repo = _BulkAuthRepo(
        {
            1: SimpleNamespace(id=1, username="reporter-a", nickname="Reporter A", status="active"),
            2: SimpleNamespace(id=2, username="reporter-b", nickname="Reporter B", status="active"),
            50: SimpleNamespace(id=50, username="target-user", nickname="Target User", status="active"),
        }
    )
    material_repo = _BulkTargetRepo(
        {301: SimpleNamespace(id=301, title="资料标题", status="VISIBLE")},
        "list_materials_by_ids",
    )
    comment_repo = _BulkTargetRepo(
        {401: SimpleNamespace(id=401, material_id=301, content="评论内容", status="visible")},
        "list_comments_by_ids",
    )
    market_repo = _BulkTargetRepo(
        {501: SimpleNamespace(id=501, title="商品标题", status="SALE")},
        "list_items_by_ids",
    )
    service = _service_with_targets(
        auth_repo=auth_repo,
        material_repo=material_repo,
        comment_repo=comment_repo,
        market_repo=market_repo,
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_report(session, report_id=1, status="PENDING", target_type="USER", target_id=50, reporter_id=1, created_at=base)
        _add_report(
            session,
            report_id=2,
            status="PENDING",
            target_type="MATERIAL",
            target_id=301,
            reporter_id=2,
            created_at=base + timedelta(minutes=1),
        )
        _add_report(
            session,
            report_id=3,
            status="PENDING",
            target_type="COMMENT",
            target_id=401,
            reporter_id=1,
            created_at=base + timedelta(minutes=2),
        )
        _add_report(
            session,
            report_id=4,
            status="PENDING",
            target_type="MARKET_ITEM",
            target_id=501,
            reporter_id=2,
            created_at=base + timedelta(minutes=3),
        )
        session.commit()

        data = service.list_for_admin(session, page=0, size=20, status_value="pending", target_type=None)

    assert auth_repo.bulk_queries == [[1, 2, 50]]
    assert auth_repo.single_queries == []
    assert material_repo.bulk_queries == [[301]]
    assert comment_repo.bulk_queries == [[401]]
    assert market_repo.bulk_queries == [[501]]
    assert [(item["targetLabel"], item["reporterName"]) for item in data["items"]] == [
        ("商品标题", "Reporter B"),
        ("评论内容", "Reporter A"),
        ("资料标题", "Reporter B"),
        ("Target User", "Reporter A"),
    ]
