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


def test_areal_metadata_bridge_preserves_signature_and_disables_thinking() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "training/runtime_shims"), str(ROOT)]
    )
    env["STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import inspect, json; "
                "from areal.experimental.openai.client import AsyncCompletionsWithReward; "
                "from areal_metadata_bridge import bridge_request_kwargs; "
                "kw=bridge_request_kwargs({'metadata': "
                "{'studyhub_chat_template':'disable_thinking_v1'}}); "
                "print(json.dumps({'patched': bool(getattr("
                "AsyncCompletionsWithReward.create, "
                "'_studyhub_metadata_bridge_v1', False)), "
                "'messages_in_signature': 'messages' in inspect.signature("
                "AsyncCompletionsWithReward.create).parameters, "
                "'enable_thinking': kw['extra_body']['chat_template_kwargs']"
                "['enable_thinking']}, sort_keys=True))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.strip() == (
        '{"enable_thinking": false, "messages_in_signature": true, '
        '"patched": true}'
    )
