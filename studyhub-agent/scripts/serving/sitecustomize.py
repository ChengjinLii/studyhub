"""No-nvcc compatibility shim for serving SGLang on this host.

This host has CUDA *runtime* libraries (via pip `nvidia-cuda-runtime-cu12`
etc.) but no CUDA *toolkit* (`nvcc`). SGLang's bundled `deep_gemm` package
unconditionally asserts that `CUDA_HOME` is set at import time (it raises
`AssertionError`, not `ImportError`, so SGLang's own
`except ImportError: return False` guard around `import deep_gemm` in
`sglang.srt.layers.deep_gemm_wrapper.configurer` does not catch it). That
crashes `sglang.launch_server` before it ever reaches a memory or model
question.

Provenance: extracted from
`git show legacy-agent-v2:studyhub-agent/training/runtime_shims/sitecustomize.py`
(studyhub repo, tag `legacy-agent-v2`, commit ff2d6d24d8bb281ae39134305e1de584c383d1e0),
lines 70-89 of that file — the two no-nvcc guards only. The legacy file's
other guards (torch determinism, AReaL bridges, LoRA adapter bridges) are
training-specific, import training-only packages that do not exist in this
foundation repo, and are unrelated to serving; they were intentionally left
out of this vendored copy.

Usage: put this file's directory on `PYTHONPATH` before launching
`python -m sglang.launch_server` (Python auto-imports `sitecustomize` at
interpreter start if its directory is on `sys.path`/`PYTHONPATH`), and set
the env vars below. See `scripts/serving/README.md` for the full launch
recipe used to serve Qwen3.5-4B on this host.
"""

from __future__ import annotations

import os
import shutil
import sys

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
