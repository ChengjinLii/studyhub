from __future__ import annotations

from types import SimpleNamespace

from app.core import db as db_module


def test_required_tables_exclude_disabled_agentic_durable_storage(monkeypatch) -> None:
    monkeypatch.setattr(
        db_module,
        "expected_table_names",
        lambda: ["agent_runs", "materials", "users"],
    )
    monkeypatch.setattr(
        db_module,
        "get_settings",
        lambda: SimpleNamespace(agentic_durable_storage_enabled=False),
    )

    assert db_module.required_table_names() == ["materials", "users"]


def test_required_tables_include_enabled_agentic_durable_storage(monkeypatch) -> None:
    monkeypatch.setattr(
        db_module,
        "expected_table_names",
        lambda: ["agent_runs", "materials", "users"],
    )
    monkeypatch.setattr(
        db_module,
        "get_settings",
        lambda: SimpleNamespace(agentic_durable_storage_enabled=True),
    )

    assert db_module.required_table_names() == ["agent_runs", "materials", "users"]
