from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from safetensors.torch import save_file

from scripts.train.record_qwen35_4b_sft2_completion import exact_adapter_match
from training.initial_adapter import load_initial_adapter, validate_adapter_config


def test_initial_adapter_contract_accepts_exact_lora_recipe() -> None:
    validate_adapter_config(
        {
            "r": 32,
            "lora_alpha": 32,
            "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
        },
        rank=32,
        alpha=32,
        target_modules=["o_proj", "gate_proj", "up_proj", "down_proj"],
    )


@pytest.mark.parametrize("field,value", [("r", 16), ("lora_alpha", 64)])
def test_initial_adapter_contract_rejects_rank_or_alpha_drift(
    field: str, value: int
) -> None:
    payload = {
        "r": 32,
        "lora_alpha": 32,
        "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
    }
    payload[field] = value
    with pytest.raises(RuntimeError, match="adapter/config mismatch"):
        validate_adapter_config(
            payload,
            rank=32,
            alpha=32,
            target_modules=["o_proj", "gate_proj", "up_proj", "down_proj"],
        )


def test_exact_adapter_match_compares_tensor_values(tmp_path: Path) -> None:
    left = tmp_path / "left.safetensors"
    right = tmp_path / "right.safetensors"
    changed = tmp_path / "changed.safetensors"
    state = {"base_model.model.x.lora_A.weight": torch.arange(8).reshape(2, 4)}
    save_file(state, left)
    save_file(state, right)
    save_file({next(iter(state)): state[next(iter(state))] + 1}, changed)
    assert exact_adapter_match(left, right)["status"] == "PASS"
    assert exact_adapter_match(left, changed)["status"] == "FAIL"


def test_nonzero_rank_defers_adapter_tensors_to_areal_broadcast(
    tmp_path: Path,
) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text(
        '{"r":32,"lora_alpha":32,"target_modules":["o_proj"]}',
        encoding="utf-8",
    )
    (adapter / "adapter_model.safetensors").write_bytes(b"rank-zero-loads-this")
    engine = SimpleNamespace(
        rank=1,
        config=SimpleNamespace(
            lora_rank=32,
            lora_alpha=32,
            target_modules=["o_proj"],
        ),
    )

    result = load_initial_adapter(engine, adapter)

    assert result["loaded_by_rank0_broadcast"] is True
