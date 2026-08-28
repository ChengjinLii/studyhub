from __future__ import annotations

import json
from pathlib import Path

import torch
from safetensors.torch import save_file

from scripts.train.verify_sft_recovery_gate import compare_adapters


def test_adapter_comparison_requires_exact_tensor_equality(tmp_path: Path) -> None:
    reference = tmp_path / "reference.safetensors"
    recovered = tmp_path / "recovered.safetensors"
    tensors = {
        "adapter.a": torch.tensor([[1.0, 2.0]], dtype=torch.bfloat16),
        "adapter.b": torch.tensor([[3.0]], dtype=torch.bfloat16),
    }
    save_file(tensors, reference)
    save_file(tensors, recovered)

    result = compare_adapters(reference, recovered)

    assert result["status"] == "PASS"
    assert result["exact_tensor_count"] == 2
    assert result["max_absolute_difference"] == 0.0


def test_adapter_comparison_rejects_any_tensor_difference(tmp_path: Path) -> None:
    reference = tmp_path / "reference.safetensors"
    recovered = tmp_path / "recovered.safetensors"
    save_file({"adapter": torch.tensor([1.0])}, reference)
    save_file({"adapter": torch.tensor([2.0])}, recovered)

    result = compare_adapters(reference, recovered)

    assert result["status"] == "FAIL"
    assert "nonidentical_tensors:1" in result["failures"]
    json.dumps(result)
