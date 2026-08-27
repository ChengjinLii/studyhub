import subprocess
import sys
from pathlib import Path

import yaml

from scripts.train.preflight_runtime_sft_v3 import _resolve_cli_path

PROJECT = Path(__file__).resolve().parents[3]


def test_runtime_sft_v3_preflight_is_directly_executable(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT / "scripts/train/preflight_runtime_sft_v3.py"), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--overnight" in result.stdout


def test_runtime_sft_v3_preflight_resolves_relative_authorization(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    assert _resolve_cli_path(Path("configs/authorization.json")) == tmp_path / "configs/authorization.json"


def test_runtime_sft_v3_config_is_bound_to_dual_gpu_dataset() -> None:
    config = yaml.safe_load((PROJECT / "configs/train/runtime-sft-v3-qwen35-9b.yaml").read_text(encoding="utf-8"))

    assert config["cluster"]["n_gpus_per_node"] == 2
    assert config["actor"]["backend"] == "fsdp:d2p1t1"
    assert config["actor"]["dtype"] == "bfloat16"
    assert config["actor"]["use_lora"] is True
    assert config["actor"]["target_modules"] == ["o_proj", "gate_proj", "up_proj", "down_proj"]
    assert config["actor"]["mb_spec"]["max_tokens_per_mb"] == 8192
    assert config["train_dataset"]["path"].endswith("runtime_sft_v3_qwen35_9b/hf_dataset")


def test_runtime_sft_v3_launcher_has_explicit_safety_gates() -> None:
    launcher = (PROJECT / "scripts/train/run_runtime_sft_v3.sh").read_text(encoding="utf-8")

    assert "STUDYHUB_ALLOW_TRAINING" in launcher
    assert "STUDYHUB_ALLOW_FORMAL_SFT" in launcher
    assert "STUDYHUB_ALLOW_DIRTY_FORMAL" in launcher
    assert "STUDYHUB_FORMAL_SFT_TRIAL" in launcher
    assert 'TRAINING_TRIAL="formal-r16-seed-20260827"' in launcher
    assert '"${SEED}" != "20260827"' in launcher
    assert 'ATTEMPT_ID="${TRAINING_TRIAL}-attempt-${TIMESTAMP}"' in launcher
    assert "FORMAL_SFT_COMPLETE.json" in launcher
    assert "record_formal_sft_completion.py" in launcher
    assert '--benchmark-manifest "${BENCHMARK_MANIFEST}"' in launcher
    assert "guarded_gpu_launch.py" in launcher
    assert "runtime-sft-v3-data-card.json" in launcher
    assert "STUDYHUB_TRAIN_GPUS:-0,1" in launcher
    assert "--model-hash-cache" in launcher
    assert "PYTORCH_ALLOC_CONF" in launcher
    assert "profile-r32) PREFLIGHT_ARGS+=(--lora-rank 32 --lora-alpha 32)" in launcher
    assert "PREFLIGHT_ARGS+=(--formal)" in launcher


def test_runtime_sft_v3_driver_captures_initial_lora() -> None:
    driver = (PROJECT / "training/sft/open_bootstrap_driver.py").read_text(encoding="utf-8")

    assert "SaveLoadMeta" in driver
    assert "_save_initial_lora_weights(trainer, config)" in driver
    assert 'name="actor"' in driver


def test_overnight_launcher_is_bounded_and_separately_authorized() -> None:
    launcher = (PROJECT / "scripts/train/run_overnight_sft_baseline.sh").read_text(encoding="utf-8")

    assert "STUDYHUB_ALLOW_OVERNIGHT_SFT" in launcher
    assert "overnight-sft-baseline-authorization.json" in launcher
    assert "--max-wall-seconds" in launcher
    assert "OVERNIGHT_SFT_BASELINE_COMPLETE.json" in launcher
    assert "record_overnight_sft_completion.py" in launcher
    assert "--overnight" in launcher
    assert "run_controlled_grpo.sh" not in launcher
    assert "sealed" not in launcher.casefold()


def test_runtime_sft_gate_has_a_tracked_promotion_tool() -> None:
    promoter = (PROJECT / "scripts/train/promote_runtime_sft_gate.py").read_text(encoding="utf-8")

    assert "lora_update_not_observed" in promoter
    assert "gpu_guard_exceeded" in promoter
    assert "It does not establish SFT quality" in promoter
