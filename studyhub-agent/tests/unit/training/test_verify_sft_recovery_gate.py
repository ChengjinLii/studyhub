from __future__ import annotations

import json
from pathlib import Path

import torch
from safetensors.torch import save_file

from scripts.train.verify_sft_recovery_gate import (
    compare_adapters,
    compare_batch_fingerprints,
    compare_run_provenance,
    load_shared_prefix_report,
    verify_state_continuity,
)


def _contract() -> dict:
    return {
        "adapter_thresholds": {
            "max_absolute_difference": 1e-5,
            "max_relative_l2_to_reference": 5e-6,
            "max_relative_l2_to_reference_update": 0.05,
            "min_update_cosine_similarity": 0.999,
            "min_update_norm_ratio": 0.995,
            "max_update_norm_ratio": 1.005,
        }
    }


def test_adapter_comparison_requires_exact_tensor_equality(tmp_path: Path) -> None:
    reference = tmp_path / "reference.safetensors"
    recovered = tmp_path / "recovered.safetensors"
    initial = tmp_path / "initial.safetensors"
    tensors = {
        "adapter.a": torch.tensor([[1.0, 2.0]], dtype=torch.bfloat16),
        "adapter.b": torch.tensor([[3.0]], dtype=torch.bfloat16),
    }
    save_file(tensors, reference)
    save_file(tensors, recovered)
    save_file({key: torch.zeros_like(value) for key, value in tensors.items()}, initial)

    result = compare_adapters(reference, recovered, initial, _contract())

    assert result["status"] == "PASS"
    assert result["equivalence_mode"] == "bitwise"
    assert result["exact_tensor_count"] == 2
    assert result["max_absolute_difference"] == 0.0


def test_adapter_comparison_rejects_any_tensor_difference(tmp_path: Path) -> None:
    reference = tmp_path / "reference.safetensors"
    recovered = tmp_path / "recovered.safetensors"
    initial = tmp_path / "initial.safetensors"
    save_file({"adapter": torch.tensor([1.0])}, reference)
    save_file({"adapter": torch.tensor([2.0])}, recovered)
    save_file({"adapter": torch.tensor([0.0])}, initial)

    result = compare_adapters(reference, recovered, initial, _contract())

    assert result["status"] == "FAIL"
    assert "max_absolute_difference_exceeded" in result["failures"]
    json.dumps(result)


def test_adapter_comparison_accepts_preregistered_numeric_drift(tmp_path: Path) -> None:
    reference = tmp_path / "reference.safetensors"
    recovered = tmp_path / "recovered.safetensors"
    initial = tmp_path / "initial.safetensors"
    expected = torch.full((1024,), 0.001, dtype=torch.float32)
    actual = expected.clone()
    actual[0] += 1e-9
    save_file({"adapter": expected}, reference)
    save_file({"adapter": actual}, recovered)
    save_file({"adapter": torch.zeros_like(expected)}, initial)

    result = compare_adapters(reference, recovered, initial, _contract())

    assert result["status"] == "PASS"
    assert result["equivalence_mode"] == "bounded_numeric"
    assert result["bitwise_equal"] is False


def _prefix_payload() -> dict:
    inventory = {
        "file_count": 3,
        "total_bytes": 30,
        "tree_sha256": "tree",
        "files": [
            {
                "path": "recover_info/dataloader_info.pkl",
                "bytes": 10,
                "sha256": "loader",
            },
            {
                "path": "recover_info/rng_state_rank_0.pt",
                "bytes": 10,
                "sha256": "rng",
            },
            {
                "path": "default/recover_checkpoint/.metadata",
                "bytes": 10,
                "sha256": "metadata",
            },
        ],
    }
    return {
        "schema_version": "studyhub.sft-shared-prefix.v2",
        "status": "PASS",
        "method": "paused_non_destructive_copy_atomic_publish",
        "source_preserved": True,
        "inventory_equal": True,
        "stability": {"status": "PASS"},
        "step_info": {"global_step": 1},
        "source_inventory": inventory,
        "target_inventory": inventory,
        "dcp_metadata_load": {
            "source": {"status": "PASS"},
            "target": {"status": "PASS"},
        },
        "runtime": {"world_size": 1},
    }


def test_shared_prefix_report_requires_non_destructive_hashed_snapshot(
    tmp_path: Path,
) -> None:
    report = tmp_path / "prefix.json"
    report.write_text(json.dumps(_prefix_payload()), encoding="utf-8")

    result = load_shared_prefix_report(report, expected_global_step=1)

    assert result["status"] == "PASS"


def _write_rows(root: Path, lane: str, rank: int, rows: list[dict]) -> None:
    directory = root / lane
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"rank-{rank}.jsonl").write_text(
        "".join(json.dumps({"rank": rank, **row}) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_batch_fingerprints_require_exact_sample_and_loss_mask_identity(
    tmp_path: Path,
) -> None:
    continuous = tmp_path / "continuous"
    recovered = tmp_path / "recovered"
    row = {
        "event": "train_batch",
        "global_step": 2,
        "batch_sha256": "batch",
        "sample_sha256": ["sample"],
        "input_ids_sha256": ["tokens"],
        "loss_mask_sha256": ["mask"],
        "sample_count": 1,
        "world_size": 1,
    }
    _write_rows(continuous, "batches", 0, [row])
    _write_rows(recovered, "batches", 0, [row])

    result = compare_batch_fingerprints(continuous, recovered, start=2, count=1)

    assert result["status"] == "PASS"
    assert result["comparisons"][0]["equal"] is True


def test_state_continuity_requires_rng_dataloader_and_engine_load(tmp_path: Path) -> None:
    continuous = tmp_path / "continuous"
    recovered = tmp_path / "recovered"
    _write_rows(
        continuous,
        "state",
        0,
        [
            {
                "event": "state_saved",
                "global_step": 1,
                "world_size": 1,
                "rng_file": {"sha256": "rng"},
                "dataloader_state_sha256": "loader",
                "post_audit_rng_restored": True,
                "engine_versions": {"default": 2},
            }
        ],
    )
    _write_rows(
        recovered,
        "state",
        0,
        [
            {
                "event": "state_restored",
                "saved_global_step": 1,
                "next_global_step": 2,
                "world_size": 1,
                "rng_file": {"sha256": "rng"},
                "dataloader_state_sha256": "loader",
                "dcp_model_optimizer_load": "PASS",
                "dataloader_load_state_dict": "PASS",
                "engine_versions": {"default": 2},
            }
        ],
    )
    report = tmp_path / "prefix.json"
    report.write_text(json.dumps(_prefix_payload()), encoding="utf-8")
    shared = load_shared_prefix_report(report, expected_global_step=1)

    result = verify_state_continuity(
        shared,
        continuous,
        recovered,
        expected_prefix_global_step=1,
    )

    assert result["status"] == "PASS"


def test_run_provenance_fails_closed_on_dataset_drift(tmp_path: Path) -> None:
    reference = tmp_path / "reference.json"
    recovered = tmp_path / "recovered.json"

    def payload(dataset_hash: str) -> dict:
        return {
            "git": {"commit": "abc", "dirty_patch_bytes": 0},
            "config": {"sha256": "config"},
            "dataset_manifest_sha256": dataset_hash,
            "benchmark": {"sha256": "benchmark"},
            "model": {
                "config_sha256": "model",
                "weight_files": [{"name": "weight", "sha256": "weight-hash"}],
            },
            "areal_upstream": {"commit": "areal"},
            "hermes_upstream": {"commit": "hermes"},
            "software": {"torch": "test"},
            "hardware": "gpu",
            "exit_status": 0,
        }

    reference.write_text(json.dumps(payload("left")), encoding="utf-8")
    recovered.write_text(json.dumps(payload("right")), encoding="utf-8")

    result = compare_run_provenance(reference, recovered)

    assert result["status"] == "FAIL"
    assert result["drift"]["dataset_manifest_sha256"] == {
        "reference": "left",
        "recovered": "right",
    }
