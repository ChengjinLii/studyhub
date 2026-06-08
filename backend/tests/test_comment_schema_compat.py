from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.repos import comment_repo as comment_repo_module
from app.repos.comment_repo import CommentRepository
from app.schemas.comments import CommentCreatePayload, CommentUpdatePayload
from app.services.comments_service import CommentsService


def _create_legacy_comment_schema():
    comment_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    uploader_id INTEGER NULL,
                    title VARCHAR(80) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    nickname VARCHAR(100) NOT NULL,
                    username VARCHAR(191) NULL,
                    avatar VARCHAR(255) NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    parent_id INTEGER NULL,
                    content TEXT NOT NULL,
                    like_count INTEGER NOT NULL DEFAULT 0,
                    reply_count INTEGER NOT NULL DEFAULT 0,
                    status VARCHAR(16) NOT NULL DEFAULT 'visible',
                    is_edited INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE comment_likes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reviewer VARCHAR(128) NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(text("INSERT INTO materials (id, uploader_id, title) VALUES (41, 7, 'Legacy material')"))
        connection.execute(text("INSERT INTO users (id, nickname, username, avatar) VALUES (7, 'Alice', 'alice', NULL)"))
    return engine


def _build_service() -> CommentsService:
    return CommentsService(
        settings=SimpleNamespace(requires_private_env_file=True, async_read_db_enabled=False),
        read_repo=SimpleNamespace(load_seed=lambda: {}),
        auth_repo=SimpleNamespace(
            find_user_by_id=lambda session, user_id: SimpleNamespace(id=user_id, nickname="Alice", username="alice", avatar=None)
        ),
        material_repo=None,
        comment_repo=CommentRepository(),
        report_service=None,
    )


def test_comment_repo_tolerates_legacy_comments_table_without_source_column() -> None:
    engine = _create_legacy_comment_schema()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO comments (
                    material_id, user_id, parent_id, content, like_count, reply_count,
                    status, is_edited, created_at, updated_at
                )
                VALUES (41, 7, NULL, 'hello', 0, 0, 'visible', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )

    with Session(engine) as session:
        comment = CommentRepository().get_comment(session, 1)

    assert comment is not None
    assert comment.content == "hello"
    assert "source" not in comment.__dict__


def test_comment_like_methods_tolerate_legacy_table_without_updated_at() -> None:
    engine = _create_legacy_comment_schema()
    repo = CommentRepository()
    with Session(engine) as session:
        created = repo.add_like(session, comment_id=1, user_id=7)
        session.commit()
        found = repo.find_like(session, 1, 7)
        assert found is not None
        assert found.id == created.id
        repo.remove_like(session, found)
        session.commit()
        assert repo.find_like(session, 1, 7) is None


def test_comment_service_compat_write_flow_uses_legacy_columns() -> None:
    engine = _create_legacy_comment_schema()
    service = _build_service()

    with Session(engine) as session:
        created = service.create(
            session,
            CommentCreatePayload(materialId=41, parentId=None, content="第一条评论"),
            user_id=7,
        )
        comment_id = int(created["id"])
        assert created["content"] == "第一条评论"
        assert created["edited"] is False

        updated = service.update(
            session,
            comment_id,
            CommentUpdatePayload(content="更新后的评论"),
            user_id=7,
            can_moderate=False,
        )
        assert updated["content"] == "更新后的评论"
        assert updated["edited"] is True

        assert service.like(session, comment_id, 7) == 1
        assert service.unlike(session, comment_id, 7) == 0

        service.delete(session, comment_id, user_id=7, can_moderate=False)
        row = session.execute(text("SELECT status, content FROM comments WHERE id = :id"), {"id": comment_id}).mappings().one()
        assert row["status"] == "deleted"
        assert row["content"] == ""
