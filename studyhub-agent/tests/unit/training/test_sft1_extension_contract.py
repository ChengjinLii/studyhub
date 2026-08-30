from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXTENSION_PATH = PROJECT_ROOT / "configs/program-v4/qwen35-4b-sft1-extension-v1.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sft1_extension_is_frozen_against_the_protocol_contract() -> None:
    extension = _load(EXTENSION_PATH)
    decision = extension["decision_source"]
    assert isinstance(decision, dict)
    protocol_path = PROJECT_ROOT / str(decision["contract_relative_path"])
    assert hashlib.sha256(protocol_path.read_bytes()).hexdigest() == decision["contract_sha256"]

    protocol = _load(protocol_path)
    thresholds = protocol["thresholds"]
    trigger = extension["trigger"]
    assert isinstance(thresholds, dict)
    assert isinstance(trigger, dict)
    run_if = trigger["run_only_if_any"]
    assert isinstance(run_if, dict)
    assert run_if["tool_call_parse_rate_below"] == thresholds["tool_call_parse_minimum"]
    assert run_if["final_nonempty_rate_below"] == thresholds["final_nonempty_minimum"]
    assert trigger["observation_mask_audit_required"] == "PASS"


def test_sft1_extension_cannot_be_selected_from_capability_benchmarks() -> None:
    extension = _load(EXTENSION_PATH)
    decision = extension["decision_source"]
    assert isinstance(decision, dict)
    assert set(decision["prohibited_decision_inputs"]) >= {
        "AgentBench",
        "BFCL",
        "tau2",
        "fresh_holdout",
        "sealed",
    }

    training = extension["training"]
    assert isinstance(training, dict)
    assert training["maximum_additional_optimizer_updates"] == 1050
    assert training["learning_rate"] == 1e-5
    assert training["global_batch_size"] == 8

    lineage = extension["lineage"]
    assert isinstance(lineage, dict)
    assert lineage["same_selected_rows_required"] is True
    assert lineage["same_tokenization_required"] is True
    assert lineage["sealed_used"] is False
    assert lineage["main_grpo_started"] is False
