"""Load a frozen LoRA checkpoint before an AReaL training stage starts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import torch

_ADAPTER_ENV = "STUDYHUB_AREAL_INITIAL_ADAPTER"
_PATCH_MARKER = "_studyhub_initial_adapter_bridge_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_adapter_config(
    payload: dict[str, Any],
    *,
    rank: int,
    alpha: int,
    target_modules: list[str],
) -> None:
    actual = {
        "r": int(payload.get("r", -1)),
        "lora_alpha": int(payload.get("lora_alpha", -1)),
    }
    expected = {"r": int(rank), "lora_alpha": int(alpha)}
    if actual != expected:
        raise RuntimeError(
            f"initial adapter/config mismatch: expected={expected}, actual={actual}"
        )
    raw_targets = payload.get("target_modules", [])
    actual_targets = (
        {str(raw_targets)}
        if isinstance(raw_targets, str)
        else {str(value) for value in raw_targets}
    )
    expected_targets = {str(value) for value in target_modules}
    if actual_targets != expected_targets:
        raise RuntimeError(
            "initial adapter target-module mismatch: "
            f"expected={sorted(expected_targets)}, actual={sorted(actual_targets)}"
        )


def load_initial_adapter(engine: Any, adapter_path: Path) -> dict[str, Any]:
    """Load one complete adapter into an already-created PEFT model."""

    path = adapter_path.resolve()
    config_path = path / "adapter_config.json"
    weights_path = path / "adapter_model.safetensors"
    if not config_path.is_file() or not weights_path.is_file():
        raise FileNotFoundError(f"incomplete initial LoRA adapter: {path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    validate_adapter_config(
        payload,
        rank=int(engine.config.lora_rank),
        alpha=int(engine.config.lora_alpha),
        target_modules=list(engine.config.target_modules),
    )

    # AReaL creates nonzero ranks on the meta device and broadcasts rank 0's
    # complete state after FSDP wrapping. Writing real tensors to those meta
    # modules is both unnecessary and version-dependent.
    if int(getattr(engine, "rank", 0)) != 0:
        return {
            "path": str(path),
            "adapter_sha256": sha256(weights_path),
            "loaded_by_rank0_broadcast": True,
            "target_modules": sorted(
                str(value) for value in engine.config.target_modules
            ),
        }

    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    state = load_file(str(weights_path), device="cpu")
    result = set_peft_model_state_dict(engine.model, state, adapter_name="default")
    unexpected_lora = [
        key for key in getattr(result, "unexpected_keys", []) if "lora_" in key
    ]
    if unexpected_lora:
        raise RuntimeError(
            f"unexpected LoRA keys while loading initial adapter: {unexpected_lora[:8]}"
        )
    lora_tensors = {key: value for key, value in state.items() if "lora_" in key}
    if not lora_tensors:
        raise RuntimeError("initial adapter contains no LoRA tensors")
    nonzero = sum(
        int(torch.count_nonzero(value).item()) for value in lora_tensors.values()
    )
    if nonzero == 0:
        raise RuntimeError("initial adapter LoRA tensors are all zero")
    return {
        "path": str(path),
        "adapter_sha256": sha256(weights_path),
        "lora_tensors": len(lora_tensors),
        "lora_nonzero_values": nonzero,
        "missing_key_count": len(getattr(result, "missing_keys", [])),
        "loaded_by_rank0_broadcast": False,
        "target_modules": sorted(str(value) for value in engine.config.target_modules),
    }


def install_areal_initial_adapter_bridge() -> None:
    """Patch only AReaL's PEFT initialization, leaving training semantics intact."""

    from areal.engine.fsdp_engine import FSDPEngine

    if getattr(FSDPEngine, _PATCH_MARKER, False):
        return
    original = FSDPEngine._apply_peft_wrapper

    def apply_peft_and_load(self: Any) -> None:
        original(self)
        raw_path = os.environ.get(_ADAPTER_ENV, "").strip()
        if raw_path and self.config.use_lora:
            self._studyhub_initial_adapter = load_initial_adapter(self, Path(raw_path))

    FSDPEngine._apply_peft_wrapper = apply_peft_and_load
    setattr(FSDPEngine, _PATCH_MARKER, True)
