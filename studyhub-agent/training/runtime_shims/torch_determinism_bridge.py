"""Strict PyTorch determinism for restart-equivalent FSDP training."""

from __future__ import annotations

import os

_REQUIRED_ENV = {
    "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
    "NCCL_ALGO": "Ring",
    "TORCH_COMPILE_DETERMINISTIC": "1",
}


def install_torch_determinism_bridge() -> None:
    """Enable deterministic kernels before AReaL creates CUDA workers."""
    mismatches = {
        key: {"expected": expected, "actual": os.environ.get(key)}
        for key, expected in _REQUIRED_ENV.items()
        if os.environ.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(f"deterministic environment mismatch: {mismatches}")

    import torch

    # warn_only=True leaves fused SDPA backward on its non-deterministic path.
    torch.use_deterministic_algorithms(True, warn_only=False)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True

    if not torch.are_deterministic_algorithms_enabled():
        raise RuntimeError("PyTorch deterministic algorithms were not enabled")
    if torch.is_deterministic_algorithms_warn_only_enabled():
        raise RuntimeError("PyTorch determinism unexpectedly uses warn-only mode")
