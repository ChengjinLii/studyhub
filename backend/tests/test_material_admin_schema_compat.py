from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.materials_service import MaterialsService


def _service() -> MaterialsService:
    return MaterialsService(
        settings=SimpleNamespace(requires_private_env_file=True),  # type: ignore[arg-type]
        read_repo=SimpleNamespace(load_seed=lambda: {}),  # type: ignore[arg-type]
        auth_repo=SimpleNamespace(),  # type: ignore[arg-type]
        material_repo=SimpleNamespace(),  # type: ignore[arg-type]
        asset_store=SimpleNamespace(),  # type: ignore[arg-type]
    )


def test_admin_material_list_uses_legacy_tags_table_in_production_mode() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NULL,
                    nickname TEXT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    school TEXT NULL,
                    college TEXT NULL,
                    major TEXT NULL,
                    grade_value TEXT NULL,
                    grade_type TEXT NULL,
                    course_category TEXT NULL,
                    price INTEGER NOT NULL DEFAULT 0,
                    is_free INTEGER NOT NULL DEFAULT 1,
                    status TEXT NULL,
                    review_status TEXT NULL,
                    uploader_id INTEGER NULL,
                    download_count INTEGER NOT NULL DEFAULT 0,
                    sales_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL,
                    deleted_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE material_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    tag TEXT NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )

    service = _service()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        session.execute(text("INSERT INTO users (id, username, nickname) VALUES (2, 'alice', 'Alice')"))
        session.execute(
            text(
                """
                INSERT INTO materials (
                    id, title, school, college, major, grade_value, grade_type, course_category,
                    price, is_free, status, review_status, uploader_id, download_count,
                    sales_count, created_at, updated_at
                )
                VALUES (
                    10, '信号与系统', 'UESTC', '信通', '通信', '大二', 'UG', 'MAJOR',
                    300, 0, 'VISIBLE', 'APPROVED', 2, 8, 3, :created_at, :created_at
                )
                """
            ),
            {"created_at": now},
        )
        session.execute(text("INSERT INTO material_tags (material_id, tag, created_at) VALUES (10, '期末', :created_at)"), {"created_at": now})
        session.commit()

        data = service.list_for_admin(session, page=0, size=5, status_value=None)

    assert data["meta"] == {"page": 0, "size": 5, "total": 1}
    assert data["items"][0]["id"] == 10
    assert data["items"][0]["tags"] == ["期末"]
    assert data["items"][0]["price"] == 3.0
