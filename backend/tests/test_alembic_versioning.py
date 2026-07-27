from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql, postgresql

from app.core.config import get_settings
from app.ops.alembic_versioning import (
    ALEMBIC_VERSION_COLUMN,
    ALEMBIC_VERSION_LENGTH,
    ALEMBIC_VERSION_TABLE,
    prepare_alembic_version_table,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class _Inspector:
    def __init__(self, *, columns: list[dict[str, object]], exists: bool = True) -> None:
        self.columns = columns
        self.exists = exists

    def has_table(self, table_name: str) -> bool:
        assert table_name == ALEMBIC_VERSION_TABLE
        return self.exists

    def get_columns(self, table_name: str) -> list[dict[str, object]]:
        assert table_name == ALEMBIC_VERSION_TABLE
        return self.columns


class _Connection:
    def __init__(self, dialect) -> None:
        self.dialect = dialect
        self.statements: list[str] = []

    def execute(self, statement: sa.TextClause) -> None:
        self.statements.append(str(statement))


def test_bootstrap_creates_a_wide_version_table_on_fresh_sqlite_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    try:
        with engine.begin() as connection:
            prepare_alembic_version_table(connection)
            columns = {column["name"]: column for column in inspect(connection).get_columns(ALEMBIC_VERSION_TABLE)}
        assert columns[ALEMBIC_VERSION_COLUMN]["type"].length == ALEMBIC_VERSION_LENGTH
    finally:
        engine.dispose()


def test_fresh_alembic_upgrade_persists_long_revision_id(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "alembic.sqlite3"
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    get_settings.cache_clear()
    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
        try:
            with engine.connect() as connection:
                revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
                version_column = next(
                    column for column in inspect(connection).get_columns(ALEMBIC_VERSION_TABLE) if column["name"] == ALEMBIC_VERSION_COLUMN
                )
            assert revision == "0007_add_agentic_data_governance"
            assert version_column["type"].length == ALEMBIC_VERSION_LENGTH
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


def test_bootstrap_widens_mysql_version_column(monkeypatch) -> None:
    connection = _Connection(mysql.dialect())
    inspector = _Inspector(columns=[{"name": ALEMBIC_VERSION_COLUMN, "type": sa.String(32)}])
    monkeypatch.setattr(sa, "inspect", lambda bind: inspector)

    prepare_alembic_version_table(connection)  # type: ignore[arg-type]

    assert connection.statements == ["ALTER TABLE alembic_version MODIFY COLUMN version_num VARCHAR(128) NOT NULL"]


def test_bootstrap_widens_postgresql_version_column(monkeypatch) -> None:
    connection = _Connection(postgresql.dialect())
    inspector = _Inspector(columns=[{"name": ALEMBIC_VERSION_COLUMN, "type": sa.String(32)}])
    monkeypatch.setattr(sa, "inspect", lambda bind: inspector)

    prepare_alembic_version_table(connection)  # type: ignore[arg-type]

    assert connection.statements == ['ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)']


def test_bootstrap_leaves_sufficiently_wide_column_unchanged(monkeypatch) -> None:
    connection = _Connection(mysql.dialect())
    inspector = _Inspector(columns=[{"name": ALEMBIC_VERSION_COLUMN, "type": sa.String(ALEMBIC_VERSION_LENGTH)}])
    monkeypatch.setattr(sa, "inspect", lambda bind: inspector)

    prepare_alembic_version_table(connection)  # type: ignore[arg-type]

    assert connection.statements == []
