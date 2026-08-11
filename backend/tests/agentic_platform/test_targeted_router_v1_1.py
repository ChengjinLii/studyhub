from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from ml.agentic_platform.sft.build_final_holdout_v2 import (
    FAMILY_COUNTS as FINAL_FAMILY_COUNTS,
)
from ml.agentic_platform.sft.build_final_holdout_v2 import (
    build_final_holdout_v2,
)
from ml.agentic_platform.sft.build_targeted_router_v1_1 import (
    EXPECTED_COMBINED_SPLIT_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    FAMILY_COUNTS,
    build_targeted_router_v1_1,
)
from ml.agentic_platform.sft.build_teacher_hidden_eval import (
    build_teacher_hidden_eval,
)
from ml.agentic_platform.sft.build_validation_dataset import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_MATERIALS_PATH,
    build_validation_dataset,
)
from ml.agentic_platform.sft.compare_v1_1_seeds import compare_seeds
from ml.agentic_platform.sft.export_llamafactory import (
    export_llamafactory_dataset,
)
from ml.agentic_platform.sft.record_final_holdout_evaluation import (
    record_final_evaluation,
)
from ml.agentic_platform.sft.spec import canonical_json, load_jsonl

pytestmark = pytest.mark.private_sft_corpus


@pytest.fixture(scope="module")
def isolated_dataset_tree(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("targeted-router-v1-1")
    original_dir = root / "original"
    build_validation_dataset(
        output_dir=original_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    original = original_dir / "router_tool_2b.jsonl"

    diagnostic_dir = root / "diagnostic"
    build_teacher_hidden_eval(
        output_dir=diagnostic_dir,
        reference_dataset_path=original,
        generated_at="2026-07-31T00:01:00+00:00",
    )
    diagnostic = diagnostic_dir / "router_hidden_300.jsonl"

    targeted_dir = root / "targeted"
    build_targeted_router_v1_1(
        reference_dataset_path=original,
        diagnostic_dataset_path=diagnostic,
        output_dir=targeted_dir,
        generated_at="2026-07-31T00:02:00+00:00",
    )
    combined = targeted_dir / "router_tool_2b_combined.jsonl"

    final_dir = root / "final"
    build_final_holdout_v2(
        original_dataset_path=original,
        combined_dataset_path=combined,
        diagnostic_dataset_path=diagnostic,
        output_dir=final_dir,
        generated_at="2026-07-31T00:03:00+00:00",
    )
    return {
        "root": root,
        "original": original,
        "diagnostic": diagnostic,
        "targeted_dir": targeted_dir,
        "combined": combined,
        "final_dir": final_dir,
    }


def test_targeted_dataset_counts_and_remediation_invariants(
    isolated_dataset_tree: dict[str, Path],
) -> None:
    targeted_dir = isolated_dataset_tree["targeted_dir"]
    rows = load_jsonl(targeted_dir / "router_tool_2b_targeted.jsonl")
    audit = json.loads((targeted_dir / "audit.json").read_text())

    assert len(rows) == 1000
    assert audit["passed"] is True
    assert audit["family_counts"] == FAMILY_COUNTS
    assert audit["split_counts"] == {
        key: value for key, value in EXPECTED_SPLIT_COUNTS.items() if value
    }
    assert audit["diversity"]["unique_query_target_pairs"] == 1000
    assert audit["diversity"]["unique_user_payloads"] == 1000
    assert audit["targeted_spec_audit"]["duplicate_pairs"] == []
    assert audit["combined_spec_audit"]["material_split_leaks"] == {}
    assert all(
        value == 0
        for key, value in audit["overlap_audit"].items()
        if key.startswith("exact_")
    )
    assert audit["overlap_audit"]["reserved_test_material_overlap"] == []
    assert all(
        row["quality"]["label_status"] == "silver_teacher_sft"
        and row["training_eligible"] is True
        and row["messages"][-1]["trainable"] is True
        for row in rows
    )

    force_final = [
        row for row in rows if row["task_family"] == "force_final_budget"
    ]
    assert all(
        json.loads(row["messages"][1]["content"])["force_final"] is True
        and set(json.loads(row["messages"][1]["content"])["budget"].values()) == {0}
        and row["assistant_target"]["mode"] == "final"
        for row in force_final
    )
    explicit_pages = [
        row for row in rows if row["task_family"] == "explicit_page_numbers"
    ]
    assert all(
        row["assistant_target"]["actions"][0]["arguments"]["page_numbers"]
        == row["remediation_contract"]["preserve_page_numbers"]
        for row in explicit_pages
    )


def test_combined_dataset_exports_with_explicit_expected_counts(
    isolated_dataset_tree: dict[str, Path],
) -> None:
    dataset_dir = isolated_dataset_tree["root"] / "llamafactory"
    manifest = export_llamafactory_dataset(
        source_path=isolated_dataset_tree["combined"],
        dataset_dir=dataset_dir,
        expected_profile_count=1500,
        expected_split_counts=EXPECTED_COMBINED_SPLIT_COUNTS,
    )

    assert manifest["counts"] == EXPECTED_COMBINED_SPLIT_COUNTS
    assert manifest["assistant_only_loss"] is True
    assert len(load_jsonl(dataset_dir / "router_tool_2b_train.jsonl")) == 1300


def test_final_holdout_is_sealed_unique_and_training_ineligible(
    isolated_dataset_tree: dict[str, Path],
) -> None:
    final_dir = isolated_dataset_tree["final_dir"]
    dataset = final_dir / "router_final_holdout_300.jsonl"
    rows = load_jsonl(dataset)
    audit = json.loads((final_dir / "audit.json").read_text())
    seal = json.loads((final_dir / "seal.json").read_text())

    assert len(rows) == 300
    assert audit["passed"] is True
    assert audit["family_counts"] == FINAL_FAMILY_COUNTS
    assert audit["unique_normalized_queries"] == 300
    assert audit["unique_user_payloads"] == 300
    assert audit["unique_targets"] == 300
    assert audit["overlap_audit"]["exact_query_overlap"] == 0
    assert audit["overlap_audit"]["exact_payload_overlap"] == 0
    assert audit["overlap_audit"]["exact_target_overlap"] == 0
    assert audit["overlap_audit"]["train_material_overlap"] == []
    assert audit["training_eligible_true"] == 0
    assert audit["trainable_messages"] == 0
    assert audit["model_inference_run"] is False
    assert seal["sealed"] is True
    assert seal["evaluated"] is False
    assert stat.S_IMODE(dataset.stat().st_mode) == 0o600
    assert all(
        row["split"] == "final_holdout_v2"
        and row["training_eligible"] is False
        and all(message["trainable"] is False for message in row["messages"])
        for row in rows
    )

    with pytest.raises(ValueError, match="failed validation"):
        export_llamafactory_dataset(
            source_path=dataset,
            dataset_dir=isolated_dataset_tree["root"] / "must-not-export-final",
            expected_profile_count=300,
            expected_split_counts={
                "train": 0,
                "validation": 0,
                "test": 0,
            },
        )


def test_final_receipt_is_hash_checked_and_single_use(
    isolated_dataset_tree: dict[str, Path],
) -> None:
    final_dir = isolated_dataset_tree["final_dir"]
    dataset = final_dir / "router_final_holdout_300.jsonl"
    rows = load_jsonl(dataset)
    predictions = final_dir / "synthetic-perfect-predictions.jsonl"
    with predictions.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            target = row["assistant_target"]
            handle.write(
                json.dumps(
                    {
                        "example_id": row["example_id"],
                        "split": row["split"],
                        "task_family": row["task_family"],
                        "expected": target,
                        "generated": canonical_json(target),
                        "parsed": target,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    adapter_dir = isolated_dataset_tree["root"] / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "adapter_model.safetensors").write_bytes(b"test-adapter")
    receipt_path = final_dir / "evaluation_receipt.json"

    receipt = record_final_evaluation(
        adapter_path=adapter_dir,
        predictions_path=predictions,
        dataset_path=dataset,
        seal_path=final_dir / "seal.json",
        receipt_path=receipt_path,
        evaluated_at="2026-07-31T00:04:00+00:00",
    )

    assert receipt["evaluation_count"] == 1
    assert receipt["analysis"]["overall"]["contract_valid"]["rate"] == 1.0
    assert (
        receipt["analysis"]["subset_metrics"]["force_final_compliant"]["rate"]
        == 1.0
    )
    assert (
        receipt["analysis"]["subset_metrics"][
            "explicit_page_number_preserved"
        ]["rate"]
        == 1.0
    )
    assert (
        receipt["analysis"]["subset_metrics"]["synthesis_contract"]["rate"]
        == 1.0
    )

    with pytest.raises(FileExistsError, match="already has"):
        record_final_evaluation(
            adapter_path=adapter_dir,
            predictions_path=predictions,
            dataset_path=dataset,
            seal_path=final_dir / "seal.json",
            receipt_path=receipt_path,
        )


def test_three_seed_comparison_applies_final_gate(
    isolated_dataset_tree: dict[str, Path],
) -> None:
    final_dir = isolated_dataset_tree["final_dir"]
    source_predictions = final_dir / "synthetic-perfect-predictions.jsonl"
    comparison_root = isolated_dataset_tree["root"] / "comparison"
    for seed in ("3407", "7703", "9109"):
        seed_dir = comparison_root / f"seed_{seed}"
        seed_dir.mkdir(parents=True)
        (seed_dir / "adapter_predictions.jsonl").write_bytes(
            source_predictions.read_bytes()
        )

    comparison = compare_seeds(root=comparison_root)

    assert comparison["selected_seed"] == "3407"
    assert comparison["final_holdout_candidate"] == "3407"
    assert all(item["final_gate_passed"] for item in comparison["ranking"])
