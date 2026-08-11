from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.agentic_platform.sft.build_teacher_hidden_eval import (
    FAMILY_COUNTS,
    build_teacher_hidden_eval,
)
from ml.agentic_platform.sft.export_llamafactory import export_llamafactory_dataset
from ml.agentic_platform.sft.spec import load_jsonl


def test_builds_training_ineligible_teacher_hidden_eval(tmp_path: Path) -> None:
    output_dir = tmp_path / "hidden-eval"
    manifest = build_teacher_hidden_eval(
        output_dir=output_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    rows = load_jsonl(output_dir / "router_hidden_300.jsonl")
    audit = json.loads((output_dir / "audit.json").read_text())

    assert manifest["records"] == 300
    assert manifest["family_counts"] == FAMILY_COUNTS
    assert manifest["audit_passed"] is True
    assert len(rows) == 300
    assert all(row["split"] == "hidden_test" for row in rows)
    assert all(row["training_eligible"] is False for row in rows)
    assert all(
        message["trainable"] is False
        for row in rows
        for message in row["messages"]
    )
    assert audit["train_material_overlap"] == []
    assert audit["exact_query_overlap"] == 0
    assert audit["exact_payload_overlap"] == 0
    assert audit["exact_target_overlap"] == 0


def test_training_exporter_rejects_hidden_eval(tmp_path: Path) -> None:
    output_dir = tmp_path / "hidden-eval"
    build_teacher_hidden_eval(
        output_dir=output_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="failed validation"):
        export_llamafactory_dataset(
            source_path=output_dir / "router_hidden_300.jsonl",
            dataset_dir=tmp_path / "must-not-export",
        )
