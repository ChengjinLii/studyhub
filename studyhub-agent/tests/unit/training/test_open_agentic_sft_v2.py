import hashlib
import json
from pathlib import Path

import yaml

from scripts.data.audit_open_agentic_semantic_dedup import semantic_task_text

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _json(relative: str) -> dict:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


def test_semantic_task_text_includes_tool_schema_and_path() -> None:
    base = {
        "messages": [{"role": "user", "content": "Get a random number."}],
        "tool_path_signature": "random_number -> FINAL",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "random_number",
                    "parameters": {
                        "type": "object",
                        "properties": {"minimum": {"type": "integer"}},
                        "required": ["minimum"],
                    },
                },
            }
        ],
    }
    changed = json.loads(json.dumps(base))
    changed["tools"][0]["function"]["name"] = "sample_integer"

    text = semantic_task_text(base)

    assert "Get a random number." in text
    assert "random_number:minimum:minimum" in text
    assert text != semantic_task_text(changed)


def test_open_agentic_recipe_matches_mixed_control() -> None:
    candidate = yaml.safe_load((PROJECT_ROOT / "configs/train/open-agentic-sft-v2-qwen35-9b.yaml").read_text())
    mixed = yaml.safe_load((PROJECT_ROOT / "configs/train/runtime-sft-v3-qwen35-9b.yaml").read_text())

    assert candidate["seed"] == mixed["seed"] == 20260827
    assert candidate["cluster"]["n_gpus_per_node"] == mixed["cluster"]["n_gpus_per_node"] == 2
    assert candidate["actor"] == mixed["actor"]
    assert candidate["train_dataset"]["batch_size"] == mixed["train_dataset"]["batch_size"] == 8
    assert candidate["train_dataset"]["path"] != mixed["train_dataset"]["path"]


def test_open_agentic_authorization_hashes_and_gates_are_bound() -> None:
    authorization = _json("configs/program-v3/open-agentic-sft-v2-authorization.json")
    paths = {
        "program_sha256": "configs/program-v3/open-agentic-sft-v2.json",
        "config_sha256": "configs/train/open-agentic-sft-v2-qwen35-9b.yaml",
        "data_card_sha256": "docs/training/OPEN_AGENTIC_SFT_V2_DATA_CARD.md",
        "data_audit_sha256": "docs/training/evidence/open-agentic-sft-v2-data-audit.json",
        "semantic_audit_sha256": ("docs/training/evidence/open-agentic-sft-v2-semantic-dedup.json"),
        "candidate_semantic_audit_sha256": ("docs/training/evidence/open-agentic-sft-v2-candidate-semantic-dedup.json"),
        "recovery_gate_sha256": (
            "docs/training/evidence/open-only-sft-v1-1-recovery-gate-cadence-210-20260829_163552.json"
        ),
    }
    for key, relative in paths.items():
        assert authorization["lineage"][key] == hashlib.sha256((PROJECT_ROOT / relative).read_bytes()).hexdigest()

    assert authorization["scope"]["no_rl"] is True
    assert authorization["scope"]["no_sealed"] is True
    assert authorization["budget"]["smoke_optimizer_updates"] == 24
    assert authorization["budget"]["planned_optimizer_updates"] == 2100
    assert authorization["recipe"]["scheduler_total_steps"] == 5456


def test_final_data_and_recovery_evidence_pass() -> None:
    audit = _json("docs/training/evidence/open-agentic-sft-v2-data-audit.json")
    semantic = _json("docs/training/evidence/open-agentic-sft-v2-semantic-dedup.json")
    recovery = _json("docs/training/evidence/open-only-sft-v1-1-recovery-gate-cadence-210-20260829_163552.json")

    assert audit["status"] == "PASS"
    assert all(audit["gates"].values())
    assert audit["loss_mask"]["rows_recomputed"] == 18_666
    assert semantic["status"] == "PASS"
    assert semantic["hard_cross_group_pairs"] == 0
    assert recovery["status"] == "PASS"
    assert recovery["gates"]["R4_final_equivalence"]["status"] == "BITWISE_RESUME_PASS"


def test_launcher_has_bounded_smoke_and_formal_modes() -> None:
    launcher = (PROJECT_ROOT / "scripts/train/run_open_agentic_sft_v2.sh").read_text()

    assert "STUDYHUB_ALLOW_OPEN_AGENTIC_SFT_V2" in launcher
    assert '"${MODE}" != "smoke"' in launcher
    assert '"${MODE}" != "formal"' in launcher
    assert "preflight_open_agentic_sft_v2.py" in launcher
    assert "STUDYHUB_TORCH_DETERMINISTIC_TRAINING=1" in launcher
    assert "STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS" in launcher
    assert "record_open_agentic_sft_completion.py" in launcher
    assert "training.sft.open_bootstrap_driver:main" in launcher
    assert "GRPO" not in launcher
