from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.community import FeedbackRecord, VolunteerApplicationRecord
from app.repos.community_repo import CommunityRepository
from app.services.community_service import CommunityService


class _NoFullListCommunityRepo(CommunityRepository):
    def list_feedbacks(self, session: Session):
        del session
        raise AssertionError("admin feedback list should not load all feedbacks")

    def list_volunteers(self, session: Session):
        del session
        raise AssertionError("admin volunteer list should not load all volunteers")


def _service() -> CommunityService:
    return CommunityService(_NoFullListCommunityRepo())


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    FeedbackRecord.__table__.create(bind=engine)
    VolunteerApplicationRecord.__table__.create(bind=engine)
    return Session(engine)


def _add_feedback(
    session: Session,
    *,
    feedback_id: int,
    type_value: str,
    status_value: str,
    created_at: datetime,
) -> None:
    session.add(
        FeedbackRecord(
            id=feedback_id,
            user_id=1,
            type=type_value,
            page="/materials",
            content="反馈内容",
            contact="contact",
            status=status_value,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def _add_volunteer(
    session: Session,
    *,
    volunteer_id: int,
    status_value: str,
    created_at: datetime,
) -> None:
    session.add(
        VolunteerApplicationRecord(
            id=volunteer_id,
            user_id=1,
            name=f"Volunteer {volunteer_id}",
            school_major_grade="电子科大 / 微电子 / 大四",
            skills_csv="FRONTEND,DESIGN",
            time_commitment="4-8h",
            portfolio_url="https://example.com",
            intro="希望参与优化",
            contact="contact",
            status=status_value,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def test_admin_feedback_list_filters_in_query_without_loading_all_feedbacks() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_feedback(session, feedback_id=1, type_value="BUG", status_value="NEW", created_at=base)
        _add_feedback(session, feedback_id=2, type_value="FEATURE", status_value="NEW", created_at=base + timedelta(minutes=1))
        _add_feedback(session, feedback_id=3, type_value="FEATURE", status_value="RESOLVED", created_at=base + timedelta(minutes=2))
        session.commit()

        items = service.list_feedbacks(session, type_value=" feature ", status_value=" new ")

    assert [item["id"] for item in items] == [2]
    assert items[0]["type"] == "FEATURE"
    assert items[0]["status"] == "NEW"


def test_admin_volunteer_list_filters_in_query_without_loading_all_volunteers() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_volunteer(session, volunteer_id=1, status_value="NEW", created_at=base)
        _add_volunteer(session, volunteer_id=2, status_value="CONTACTED", created_at=base + timedelta(minutes=1))
        _add_volunteer(session, volunteer_id=3, status_value="CONTACTED", created_at=base + timedelta(minutes=2))
        session.commit()

        items = service.list_volunteers(session, status_value=" contacted ")

    assert [item["id"] for item in items] == [3, 2]
    assert items[0]["skills"] == ["FRONTEND", "DESIGN"]
