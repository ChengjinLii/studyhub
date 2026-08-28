import hashlib
import json
from pathlib import Path

import yaml

from scripts.data.build_open_only_sft_v1 import InventoryRow, select_fixed_count_for_tokens

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _inventory_row(index: int, assistant_tokens: int) -> InventoryRow:
    return InventoryRow(
        record_id=f"row-{index}",
        source="source",
        split="train",
        group_id=f"group-{index}",
        position=index,
        total_tokens=assistant_tokens + 10,
        assistant_tokens=assistant_tokens,
        stable_order=f"{index:04d}",
    )


def test_token_selector_preserves_count_and_hits_feasible_target() -> None:
    rows = [_inventory_row(index, tokens) for index, tokens in enumerate(range(10, 110, 10))]

    selected = select_fixed_count_for_tokens(rows, count=4, target_tokens=220)

    assert len(selected) == 4
    assert len({row.record_id for row in selected}) == 4
    assert sum(row.assistant_tokens for row in selected) == 220


def test_program_changes_only_training_data() -> None:
    program = json.loads(
        (PROJECT_ROOT / "configs/program-v3/open-only-sft-v1.json").read_text(encoding="utf-8")
    )
    selection = program["selection"]

    assert program["scope"]["only_training_data_changes"] is True
    assert program["scope"]["no_rl"] is True
    assert program["scope"]["no_sealed"] is True
    assert sum(selection["train_source_rows"].values()) == selection["train_rows"] == 16_800
    assert (
        sum(selection["train_source_assistant_loss_token_targets"].values())
        == selection["target_assistant_loss_tokens"]
        == 3_138_019
    )
    assert set(selection["train_source_rows"]) == set(program["allowed_sources"])


def test_open_only_recipe_matches_mixed_control() -> None:
    open_only = yaml.safe_load(
        (PROJECT_ROOT / "configs/train/open-only-sft-v1-qwen35-9b.yaml").read_text(encoding="utf-8")
    )
    mixed = yaml.safe_load(
        (PROJECT_ROOT / "configs/train/runtime-sft-v3-qwen35-9b.yaml").read_text(encoding="utf-8")
    )

    assert open_only["seed"] == mixed["seed"] == 20260827
    assert open_only["cluster"]["n_gpus_per_node"] == mixed["cluster"]["n_gpus_per_node"] == 2
    assert open_only["actor"]["path"] == mixed["actor"]["path"]
    assert open_only["actor"]["backend"] == mixed["actor"]["backend"] == "fsdp:d2p1t1"
    assert open_only["actor"]["dtype"] == mixed["actor"]["dtype"] == "bfloat16"
    assert open_only["actor"]["lora_rank"] == mixed["actor"]["lora_rank"] == 16
    assert open_only["actor"]["lora_alpha"] == mixed["actor"]["lora_alpha"] == 16
    assert open_only["actor"]["target_modules"] == mixed["actor"]["target_modules"]
    assert open_only["actor"]["optimizer"] == mixed["actor"]["optimizer"]
    assert open_only["train_dataset"]["batch_size"] == mixed["train_dataset"]["batch_size"] == 8
    assert open_only["train_dataset"]["path"] != mixed["train_dataset"]["path"]


def test_launcher_requires_explicit_open_only_authorization() -> None:
    launcher = (PROJECT_ROOT / "scripts/train/run_open_only_sft_v1.sh").read_text(encoding="utf-8")

    assert "STUDYHUB_ALLOW_TRAINING" in launcher
    assert "STUDYHUB_ALLOW_OPEN_ONLY_SFT" in launcher
    assert "preflight_open_only_sft_v1.py" in launcher
    assert "training.sft.open_bootstrap_driver:main" in launcher
    assert "GRPO" not in launcher


def test_corrected_open_only_config_preserves_the_sft_schema() -> None:
    original = yaml.safe_load(
        (PROJECT_ROOT / "configs/train/open-only-sft-v1-qwen35-9b.yaml").read_text(
            encoding="utf-8"
        )
    )
    corrected = yaml.safe_load(
        (PROJECT_ROOT / "configs/train/open-only-sft-v1.1-qwen35-9b.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert set(corrected) == set(original)
    assert corrected["actor"] == original["actor"]
    assert corrected["train_dataset"] == original["train_dataset"]
    assert corrected["valid_dataset"] == original["valid_dataset"]
    assert corrected["experiment_name"] != original["experiment_name"]
    assert corrected["cluster"]["name_resolve"] != original["cluster"]["name_resolve"]


def test_corrected_authorization_locks_the_real_config_hash() -> None:
    config = PROJECT_ROOT / "configs/train/open-only-sft-v1.1-qwen35-9b.yaml"
    authorization = json.loads(
        (
            PROJECT_ROOT
            / "configs/program-v3/open-only-sft-v1.1-lrmatched-authorization.json"
        ).read_text(encoding="utf-8")
    )

    assert authorization["lineage"]["config_sha256"] == hashlib.sha256(
        config.read_bytes()
    ).hexdigest()
    assert authorization["recipe"]["scheduler_total_steps"] == 5_456
    assert authorization["completion_contract"]["require_lr_schedule_audit"] is True


def test_corrected_launcher_fails_closed_on_scheduler_and_recovery() -> None:
    launcher = (PROJECT_ROOT / "scripts/train/run_open_only_sft_v1_1.sh").read_text(
        encoding="utf-8"
    )

    assert "STUDYHUB_ALLOW_OPEN_ONLY_SFT_V1_1" in launcher
    assert "STUDYHUB_AREAL_SCHEDULER_BRIDGE=1" in launcher
    assert "STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS" in launcher
    assert "STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP" in launcher
    assert '"${VENV_DIR}/bin/python" -S - "${RECOVER_STEP_INFO}"' in launcher
    assert '[[ ! "${ATTEMPT_START_STEP}" =~ ^[0-9]+$ ]]' in launcher
    assert "collect_lr_audit_segments.py" in launcher
    assert "audit_sft_lr_schedule.py" in launcher
    assert '--lr-audit "${LR_AUDIT}"' in launcher
    assert "OPEN_ONLY_SFT_V1_1_COMPLETE.json" in launcher
    assert "run_controlled_grpo.sh" not in launcher


def test_recovery_gate_compares_continuous_and_resumed_lora() -> None:
    launcher = (
        PROJECT_ROOT / "scripts/train/run_open_only_sft_v1_1_recovery_gate.sh"
    ).read_text(encoding="utf-8")

    assert "STUDYHUB_ALLOW_SFT_RECOVERY_GATE" in launcher
    assert 'run_attempt "${CONTINUOUS_TRIAL}"' in launcher
    assert 'run_attempt "${RECOVERED_TRIAL}"' in launcher
    assert "verify_sft_recovery_gate.py" in launcher
    assert "--continuous-adapter" in launcher
    assert "--recovered-adapter" in launcher
    assert "EXPECTED_UPDATES=4" in launcher
    assert '"${VENV_DIR}/bin/python" -S - "${RECOVER_STEP_INFO}"' in launcher
    assert '[[ ! "${recover_step}" =~ ^[0-9]+$ ]]' in launcher
    assert "GRPO" not in launcher
