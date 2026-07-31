from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0008_material_submission_idempotency.py"
)


class FakeInspector:
    def __init__(self, *, has_column: bool, has_index: bool) -> None:
        self.has_column = has_column
        self.has_index = has_index

    def get_table_names(self) -> list[str]:
        return ["materials"]

    def get_columns(self, _table_name: str) -> list[dict[str, str]]:
        columns = ["id", "uploader_id"]
        if self.has_column:
            columns.append("submission_key")
        return [{"name": name} for name in columns]

    def get_indexes(self, _table_name: str) -> list[dict[str, object]]:
        if not self.has_index:
            return []
        return [{"name": "uq_materials_uploader_submission_key", "unique": True}]

    def get_unique_constraints(self, _table_name: str) -> list[dict[str, object]]:
        return []


def _load_migration() -> Any:
    spec = importlib.util.spec_from_file_location("studyhub_alembic_0008", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_adds_only_missing_submission_column_and_unique_index(monkeypatch) -> None:
    migration = _load_migration()
    inspector = FakeInspector(has_column=False, has_index=False)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    fake_op = SimpleNamespace(
        get_bind=lambda: object(),
        add_column=lambda *args, **kwargs: calls.append(("add_column", args, kwargs)),
        create_index=lambda *args, **kwargs: calls.append(("create_index", args, kwargs)),
    )
    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    migration.upgrade()

    assert [call[0] for call in calls] == ["add_column", "create_index"]
    assert calls[0][1][1].name == "submission_key"
    assert calls[1][1][:3] == (
        "uq_materials_uploader_submission_key",
        "materials",
        ["uploader_id", "submission_key"],
    )
    assert calls[1][2]["unique"] is True


def test_migration_is_idempotent_when_schema_is_current(monkeypatch) -> None:
    migration = _load_migration()
    inspector = FakeInspector(has_column=True, has_index=True)
    fake_op = SimpleNamespace(
        get_bind=lambda: object(),
        add_column=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected add_column")),
        create_index=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected create_index")),
    )
    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    migration.upgrade()
