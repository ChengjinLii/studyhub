from __future__ import annotations

import json
from pathlib import Path

import torch
from safetensors.torch import save_file

from scripts.train.verify_sft_recovery_gate import (
    compare_adapters,
    load_shared_prefix_report,
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


def test_shared_prefix_report_requires_atomic_step_one_snapshot(tmp_path: Path) -> None:
    report = tmp_path / "prefix.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "studyhub.sft-shared-prefix.v1",
                "status": "PASS",
                "method": "atomic_directory_rename_same_filesystem",
                "step_info": {"global_step": 1},
            }
        ),
        encoding="utf-8",
    )

    result = load_shared_prefix_report(report)

    assert result["status"] == "PASS"
