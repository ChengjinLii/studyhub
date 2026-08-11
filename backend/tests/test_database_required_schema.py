from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import db as db_module


def _settings(**overrides) -> SimpleNamespace:
    values = {
        "agentic_platform_enabled": False,
        "agentic_proactive_enabled": False,
        "agentic_execution_enabled": False,
        "agentic_durable_storage_enabled": False,
        "deep_research_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_required_tables_exclude_disabled_agentic_features(monkeypatch) -> None:
    monkeypatch.setattr(
        db_module,
        "expected_table_names",
        lambda: ["agent_runs", "materials", "users"],
    )
    monkeypatch.setattr(
        db_module,
        "get_settings",
        _settings,
    )

    assert db_module.required_table_names() == ["materials", "users"]


@pytest.mark.parametrize(
    "enabled_flag",
    [
        "agentic_platform_enabled",
        "agentic_proactive_enabled",
        "agentic_execution_enabled",
        "agentic_durable_storage_enabled",
        "deep_research_enabled",
    ],
)
def test_required_tables_include_any_enabled_agentic_feature(monkeypatch, enabled_flag: str) -> None:
    monkeypatch.setattr(
        db_module,
        "expected_table_names",
        lambda: ["agent_runs", "materials", "users"],
    )
    monkeypatch.setattr(
        db_module,
        "get_settings",
        lambda: _settings(**{enabled_flag: True}),
    )

    assert db_module.required_table_names() == ["agent_runs", "materials", "users"]
