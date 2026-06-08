from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0002_add_market_source_and_order_uploader.py"
)


class FakeInspector:
    def __init__(self, *, tables: set[str], columns: dict[str, set[str]], indexes: dict[str, set[str]]) -> None:
        self.tables = tables
        self.columns = columns
        self.indexes = indexes

    def get_table_names(self) -> list[str]:
        return sorted(self.tables)

    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        return [{"name": column} for column in sorted(self.columns.get(table_name, set()))]

    def get_indexes(self, table_name: str) -> list[dict[str, str]]:
        return [{"name": index} for index in sorted(self.indexes.get(table_name, set()))]


class FakeOp:
    def __init__(self, inspector: FakeInspector | None = None) -> None:
        self.inspector = inspector
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def get_bind(self) -> object:
        return object()

    def add_column(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("add_column", args, kwargs))
        if self.inspector is not None and len(args) >= 2:
            self.inspector.columns.setdefault(str(args[0]), set()).add(str(args[1].name))

    def create_index(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("create_index", args, kwargs))


def load_migration_module() -> Any:
    spec = importlib.util.spec_from_file_location("studyhub_alembic_0002", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p0_alembic_migration_adds_only_missing_fields_and_index(monkeypatch) -> None:
    migration = load_migration_module()
    inspector = FakeInspector(
        tables={"market_items", "orders"},
        columns={"market_items": {"id"}, "orders": {"id"}},
        indexes={"orders": set()},
    )
    fake_op = FakeOp(inspector)

    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration.sa, "inspect", lambda bind: inspector)

    migration.upgrade()

    assert [call[0] for call in fake_op.calls] == ["add_column", "add_column", "create_index"]
    assert fake_op.calls[0][1][0] == "market_items"
    assert fake_op.calls[0][1][1].name == "source"
    assert fake_op.calls[1][1][0] == "orders"
    assert fake_op.calls[1][1][1].name == "uploader_id"
    assert fake_op.calls[2][1] == ("ix_orders_uploader_id", "orders", ["uploader_id"])


def test_p0_alembic_migration_is_idempotent_when_fields_exist(monkeypatch) -> None:
    migration = load_migration_module()
    fake_op = FakeOp()
    inspector = FakeInspector(
        tables={"market_items", "orders"},
        columns={"market_items": {"id", "source"}, "orders": {"id", "uploader_id"}},
        indexes={"orders": {"ix_orders_uploader_id"}},
    )

    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration.sa, "inspect", lambda bind: inspector)

    migration.upgrade()

    assert fake_op.calls == []


def test_p0_alembic_downgrade_preserves_user_data(monkeypatch) -> None:
    migration = load_migration_module()
    fake_op = SimpleNamespace(
        drop_column=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("drop_column called"))
    )

    monkeypatch.setattr(migration, "op", fake_op)

    migration.downgrade()
