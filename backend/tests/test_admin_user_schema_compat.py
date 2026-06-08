from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.auth import LegacyAuthUser
from app.repos import auth_repo as auth_repo_module
from app.repos.admin_repo import AdminRepository
from app.repos.auth_repo import AuthRepository
from app.schemas.admin import AdminCreateUserNotePayload
from app.services.admin_user_service import AdminUserService


class _DummyReadRepo:
    def load_seed(self):
        return {}


def test_admin_user_list_uses_legacy_users_table_when_auth_users_is_absent() -> None:
    auth_repo_module._USER_MODEL_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    LegacyAuthUser.__table__.create(bind=engine)
    service = AdminUserService(
        _DummyReadRepo(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        AuthRepository(),
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            LegacyAuthUser(
                id=1,
                username="admin",
                nickname="管理员",
                role_mask=31,
                verified=True,
                free_download_quota=200,
                email_privacy=False,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

        users = service.list_users(session, keyword="admin")

    assert users[0]["id"] == 1
    assert users[0]["username"] == "admin"


def test_admin_user_notes_tolerate_legacy_admin_id_column() -> None:
    auth_repo_module._USER_MODEL_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    LegacyAuthUser.__table__.create(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE user_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    admin_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
    service = AdminUserService(
        _DummyReadRepo(),  # type: ignore[arg-type]
        AdminRepository(),
        AuthRepository(),
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        session.add_all(
            [
                LegacyAuthUser(
                    id=2,
                    username="admin",
                    nickname="管理员",
                    role_mask=31,
                    verified=True,
                    free_download_quota=200,
                    email_privacy=False,
                    status="active",
                    created_at=now,
                    updated_at=now,
                ),
                LegacyAuthUser(
                    id=6,
                    username="student",
                    nickname="学生",
                    role_mask=1,
                    verified=True,
                    free_download_quota=200,
                    email_privacy=False,
                    status="active",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.execute(
            text("INSERT INTO user_notes (user_id, admin_id, message, created_at) VALUES (6, 2, 'legacy note', :created_at)"),
            {"created_at": now},
        )
        session.commit()

        notes = service.list_notes(session, 6)
        created = service.create_note(session, 6, 2, AdminCreateUserNotePayload(message="new note"))
        rows = session.execute(text("SELECT admin_id, message FROM user_notes WHERE user_id = 6 ORDER BY id")).mappings().all()

    assert notes[0]["adminId"] == 2
    assert notes[0]["adminUsername"] == "admin"
    assert notes[0]["message"] == "legacy note"
    assert created["adminId"] == 2
    assert [dict(row) for row in rows] == [
        {"admin_id": 2, "message": "legacy note"},
        {"admin_id": 2, "message": "new note"},
    ]
