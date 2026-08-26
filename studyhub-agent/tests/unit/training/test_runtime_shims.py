from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_sglang_falls_back_when_optional_deep_gemm_has_no_nvcc() -> None:
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent)
    env["PYTHONPATH"] = str(ROOT / "training/runtime_shims")
    env["STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from sglang.srt.layers.deep_gemm_wrapper.configurer "
                "import ENABLE_JIT_DEEPGEMM; print(ENABLE_JIT_DEEPGEMM)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.strip() == "False"


def test_sglang_clamp_position_uses_torch_without_nvcc() -> None:
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent)
    env["PYTHONPATH"] = str(ROOT / "training/runtime_shims")
    env["STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import torch; "
                "from sglang.jit_kernel.clamp_position import clamp_position_cuda; "
                "print(clamp_position_cuda(torch.tensor([0, 2, 5])).tolist())"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.strip() == "[0, 1, 4]"
