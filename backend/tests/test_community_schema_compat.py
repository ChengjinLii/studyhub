from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.community import NotificationRecord, VolunteerApplicationRecord
from app.repos import community_repo as community_repo_module
from app.repos.community_repo import CommunityRepository


def test_notifications_tolerate_legacy_admin_id_column() -> None:
    community_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NULL,
                    admin_id INTEGER NULL,
                    message TEXT NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )

    repo = CommunityRepository()
    with Session(engine) as session:
        saved = repo.save_notification(
            session,
            NotificationRecord(admin_user_id=1, user_id=7, message="hello"),
        )
        session.commit()

        items = repo.list_notifications_for_user(session, 7)

    assert saved.id == 1
    assert len(items) == 1
    assert items[0].admin_user_id == 1
    assert items[0].user_id == 7
    assert items[0].message == "hello"


def test_volunteers_tolerate_legacy_skills_column() -> None:
    community_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE volunteer_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NULL,
                    name TEXT NOT NULL,
                    school_major_grade TEXT NOT NULL,
                    skills TEXT NULL,
                    time_commitment TEXT NULL,
                    portfolio_url TEXT NULL,
                    intro TEXT NOT NULL,
                    contact TEXT NULL,
                    status TEXT NOT NULL,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL
                )
                """
            )
        )

    repo = CommunityRepository()
    with Session(engine) as session:
        saved = repo.save_volunteer(
            session,
            VolunteerApplicationRecord(
                user_id=7,
                name="Alice",
                school_major_grade="UESTC",
                skills_csv="FRONTEND,BACKEND",
                intro="hello",
                status="NEW",
            ),
        )
        session.commit()

        items = repo.list_volunteers_for_admin(session, status_value=None)

    assert saved.id == 1
    assert len(items) == 1
    assert items[0].skills_csv == "FRONTEND,BACKEND"
