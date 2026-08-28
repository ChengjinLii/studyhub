from __future__ import annotations

import json
import math
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
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "training/runtime_shims"), str(ROOT)])
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

    assert result.stdout.strip().splitlines()[-1] == (
        '{"enable_thinking": false, "messages_in_signature": true, "patched": true}'
    )


def test_areal_scheduler_bridge_overrides_horizon_and_reconstructs_lr() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "training/runtime_shims"), str(ROOT)])
    env["STUDYHUB_AREAL_SCHEDULER_BRIDGE"] = "1"
    env["STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS"] = "5456"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, torch; "
                "from areal.api import FinetuneSpec; "
                "from areal.engine.fsdp_engine import FSDPEngine; "
                "from areal.engine.fsdp_utils import get_cosine_schedule_with_warmup; "
                "from areal_scheduler_bridge import align_lr_scheduler; "
                "p=torch.nn.Parameter(torch.ones(1)); "
                "o=torch.optim.Adam([p], lr=2e-5); "
                "s=get_cosine_schedule_with_warmup(o, 163, 5456); "
                "e=type('Engine', (), {'optimizer':o, 'lr_scheduler':s})(); "
                "lr=align_lr_scheduler(e, 1890); "
                "spec=FinetuneSpec(total_train_epochs=1, dataset_size=16800, train_batch_size=8); "
                "print(json.dumps({'horizon':spec.total_train_steps, "
                "'steps_per_epoch':spec.steps_per_epoch, 'last_epoch':s.last_epoch, "
                "'lr':lr, 'optimizer_lr':o.param_groups[0]['lr'], "
                "'loader_patched':bool(getattr(FSDPEngine._load_from_dcp, "
                "'_studyhub_scheduler_recovery_v1', False))}, sort_keys=True))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["horizon"] == 5456
    assert payload["steps_per_epoch"] == 2100
    assert payload["last_epoch"] == 1890
    assert payload["loader_patched"] is True
    assert math.isclose(payload["lr"], 1.519065700221957e-05, rel_tol=1e-12)
    assert payload["optimizer_lr"] == payload["lr"]


def test_areal_scheduler_bridge_requires_an_explicit_horizon() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "training/runtime_shims")
    env["STUDYHUB_AREAL_SCHEDULER_BRIDGE"] = "1"
    env.pop("STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS", None)

    result = subprocess.run(
        [sys.executable, "-c", "print('must-not-run')"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "StudyHub AReaL scheduler bridge failed" in result.stderr
    assert "missing required scheduler bridge variable" in result.stderr
