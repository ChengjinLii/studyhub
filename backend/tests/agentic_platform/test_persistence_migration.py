from __future__ import annotations

import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.models.agentic_runtime import (
    AgentArtifactRecord,
    AgentJobRecord,
    AgentRunRecord,
    AgentStepRecord,
    AgentThreadRecord,
    AgentWaitRecord,
)


MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0005_add_agentic_runtime_tables.py"
RUNTIME_TABLE_NAMES = {"agent_threads", "agent_runs", "agent_steps", "agent_waits", "agent_jobs", "agent_artifacts"}


def _load_migration() -> Any:
    spec = importlib.util.spec_from_file_location("studyhub_alembic_0005", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agentic_runtime_migration_up_and_down_on_sqlite(monkeypatch) -> None:
    migration = _load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: connection))

        migration.upgrade()
        assert RUNTIME_TABLE_NAMES.issubset(set(inspect(connection).get_table_names()))
        migration.upgrade()
        assert RUNTIME_TABLE_NAMES.issubset(set(inspect(connection).get_table_names()))

        migration.downgrade()
        assert not RUNTIME_TABLE_NAMES & set(inspect(connection).get_table_names())
    engine.dispose()


def test_agentic_runtime_metadata_compiles_without_mysql_json_types() -> None:
    tables = (
        AgentThreadRecord.__table__,
        AgentRunRecord.__table__,
        AgentStepRecord.__table__,
        AgentWaitRecord.__table__,
        AgentJobRecord.__table__,
        AgentArtifactRecord.__table__,
    )
    ddl = "\n".join(str(CreateTable(table).compile(dialect=mysql.dialect())) for table in tables)

    assert re.search(r"\bJSON\b", ddl.upper()) is None
    assert "TEXT" in ddl.upper()
    assert "agent_artifacts" in ddl
