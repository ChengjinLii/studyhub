"""Process-local compatibility hooks for the pinned training runtime."""

from __future__ import annotations

import os
import shutil
import sys

if os.environ.get("STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE") == "1":
    from areal_metadata_bridge import install_areal_metadata_bridge

    install_areal_metadata_bridge()


if os.environ.get("STUDYHUB_AREAL_SCHEDULER_BRIDGE") == "1":
    try:
        from areal_scheduler_bridge import install_areal_scheduler_bridge

        install_areal_scheduler_bridge()
    except Exception as exc:
        sys.stderr.write(f"StudyHub AReaL scheduler bridge failed: {exc}\n")
        sys.stderr.flush()
        os._exit(78)


if os.environ.get("STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC") == "1" and shutil.which("nvcc") is None:
    # SGLang treats DeepGEMM as optional, but the bundled module eagerly
    # asserts when only the CUDA runtime (not the compiler toolkit) exists.
    sys.modules["deep_gemm"] = None


if os.environ.get("STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC") == "1" and shutil.which("nvcc") is None:
    import torch
    from sglang.jit_kernel import clamp_position as _clamp_position_module

    def _clamp_position_native(seq_lens: torch.Tensor) -> torch.Tensor:
        return torch.clamp(seq_lens - 1, min=0).to(torch.int64)

    _clamp_position_module.clamp_position_cuda = _clamp_position_native
