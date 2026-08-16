from __future__ import annotations

from pathlib import Path

import pytest

from studyhub_rag.config import EXPERIMENT_ROOT
from studyhub_rag.guards import require_experiment_output, require_static_snapshot, verify_source_isolation


def test_static_snapshot_rejects_database_and_escape(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    metadata = snapshot / "materials.json"
    metadata.write_text("[]", encoding="utf-8")
    assert require_static_snapshot(metadata, snapshot) == metadata.resolve()
    with pytest.raises(ValueError, match="database|Database"):
        database = snapshot / "production.sqlite3"
        database.write_text("", encoding="utf-8")
        require_static_snapshot(database, snapshot)
    with pytest.raises(ValueError, match="snapshot root"):
        require_static_snapshot(tmp_path / "outside.json", snapshot)
    with pytest.raises(ValueError, match="local snapshot"):
        require_static_snapshot("mysql://example/studyhub", snapshot)


def test_outputs_are_confined_to_experiment_root(tmp_path: Path) -> None:
    assert require_experiment_output(EXPERIMENT_ROOT / "artifacts" / "unit-test")
    with pytest.raises(ValueError, match="must remain"):
        require_experiment_output(tmp_path / "outside")


def test_current_source_has_no_backend_or_database_imports() -> None:
    assert verify_source_isolation() == []


def test_isolation_scanner_finds_forbidden_import(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import sqlite3\n", encoding="utf-8")
    violations = verify_source_isolation(tmp_path)
    assert len(violations) == 1
    assert "sqlite3" in violations[0]
