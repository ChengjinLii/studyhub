from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.repos import material_repo as material_repo_module
from app.repos.material_repo import MaterialRepository
from app.services.materials_service import MaterialsService


def _service_with_material_repo() -> MaterialsService:
    return MaterialsService(
        settings=object(),
        read_repo=type("_ReadRepo", (), {"load_seed": lambda self: {}})(),
        auth_repo=None,
        material_repo=MaterialRepository(),
        asset_store=None,
    )


def test_get_material_tolerates_legacy_materials_table_without_source_column() -> None:
    material_repo_module._TABLE_NAME_CACHE.clear()
    material_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(80) NOT NULL,
                    preview_source VARCHAR(16) NOT NULL DEFAULT 'AUTO',
                    status VARCHAR(16) NOT NULL DEFAULT 'VISIBLE',
                    deleted_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO materials (id, title, preview_source, status, deleted_at)
                VALUES (41, 'Legacy material', 'AUTO', 'VISIBLE', NULL)
                """
            )
        )

    with Session(engine) as session:
        material = MaterialRepository().get_material(session, 41)

    assert material is not None
    assert material.id == 41
    assert material.title == "Legacy material"
    assert material.preview_source == "AUTO"
    assert "source" not in material.__dict__


def test_material_like_methods_tolerate_legacy_table_without_updated_at() -> None:
    material_repo_module._TABLE_NAME_CACHE.clear()
    material_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE material_likes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )

    repo = MaterialRepository()
    with Session(engine) as session:
        created = repo.add_like(session, material_id=41, user_id=7)
        session.commit()
        found = repo.find_like(session, 41, 7)
        assert found is not None
        assert found.id == created.id
        repo.remove_like(session, found)
        session.commit()
        assert repo.find_like(session, 41, 7) is None


def test_material_view_methods_tolerate_legacy_viewed_at_table() -> None:
    material_repo_module._TABLE_NAME_CACHE.clear()
    material_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE material_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NULL,
                    viewer_token_hash VARCHAR(128) NULL,
                    viewed_at DATETIME NULL
                )
                """
            )
        )

    repo = MaterialRepository()
    with Session(engine) as session:
        created = repo.add_view(session, material_id=41, user_id=None, viewer_token_hash="token")
        session.commit()
        found = repo.find_view_by_token_hash(session, 41, "token")
        assert found is not None
        assert found.id == created.id
        assert found.user_id is None
        repo.bind_view_to_user(session, found, 7)
        session.commit()
        assert repo.find_view_by_user(session, 41, 7) is not None


def test_material_download_methods_tolerate_legacy_table_without_updated_at() -> None:
    material_repo_module._TABLE_NAME_CACHE.clear()
    material_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE material_downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )

    repo = MaterialRepository()
    with Session(engine) as session:
        assert repo.has_download(session, 41, 7) is False
        repo.add_download(session, material_id=41, user_id=7)
        session.commit()
        assert repo.has_download(session, 41, 7) is True


def test_material_like_service_does_not_reload_missing_material_columns_after_commit() -> None:
    material_repo_module._TABLE_NAME_CACHE.clear()
    material_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(80) NOT NULL,
                    preview_source VARCHAR(16) NOT NULL DEFAULT 'AUTO',
                    status VARCHAR(16) NOT NULL DEFAULT 'VISIBLE',
                    like_count INTEGER NOT NULL DEFAULT 0,
                    deleted_at DATETIME NULL,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE material_likes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO materials (id, title, preview_source, status, like_count, deleted_at)
                VALUES (41, 'Legacy material', 'AUTO', 'VISIBLE', 0, NULL)
                """
            )
        )

    service = _service_with_material_repo()
    with Session(engine) as session:
        assert service.like(session, 41, 7) == 1
        assert service.unlike(session, 41, 7) == 0
