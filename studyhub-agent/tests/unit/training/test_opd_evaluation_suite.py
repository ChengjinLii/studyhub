import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts.train.merge_sft_lora import completion_lineage
from scripts.train.run_qwen35_4b_opd_evaluation_suite import paired_agentbench


def marker_fixture(tmp_path):
    weights = tmp_path / "adapter_model.safetensors"
    weights.write_bytes(b"test weights")
    marker = tmp_path / "complete.json"
    value = {
        "status": "OPD_COMPLETE",
        "mode": "formal",
        "optimizer_updates": 300,
        "sealed_used": False,
        "main_grpo_started": False,
        "failures": [],
        "initialization": {"status": "PASS"},
        "authorization_sha256": "authorization",
        "trainer_metrics_sha256": "metrics",
        "checkpoint": {
            "path": str(weights),
            "sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
            "global_step": 299,
            "lora_updated": True,
        },
    }
    marker.write_text(json.dumps(value))
    return marker, value


def test_opd_merge_keeps_opd_lineage(tmp_path):
    marker, value = marker_fixture(tmp_path)
    result = completion_lineage(marker, "opd")
    assert result["training_method"] == "opd"
    assert result["checkpoint_sha256"] == value["checkpoint"]["sha256"]
    assert "rl_started" not in result  # Never relabel distillation as SFT-only.


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "OPD_PILOT_PASS"),
        ("optimizer_updates", 250),
        ("sealed_used", True),
        ("main_grpo_started", True),
        ("failures", ["bad gradient"]),
    ],
)
def test_opd_merge_rejects_incomplete_or_unsafe_marker(tmp_path, field, value):
    marker, content = marker_fixture(tmp_path)
    content[field] = value
    marker.write_text(json.dumps(content))
    with pytest.raises(RuntimeError, match="completed 300"):
        completion_lineage(marker, "opd")


def test_opd_merge_rejects_hash_drift(tmp_path):
    marker, value = marker_fixture(tmp_path)
    Path(value["checkpoint"]["path"]).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="hash drift"):
        completion_lineage(marker, "opd")


def test_paired_comparison_excludes_infra(tmp_path):
    rows = [
        {
            "task_id": str(i),
            "sample_seed": i,
            "split": "development",
            "status": "SCORED",
            "evaluation": {"strict_success": i == 0},
        }
        for i in range(51)
    ]
    left, right = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    left.write_text("\n".join(map(json.dumps, rows)))
    rows[0]["evaluation"]["strict_success"] = False
    rows[1]["evaluation"]["strict_success"] = True
    rows[2]["status"] = "INFRA_EXCLUDED"
    right.write_text("\n".join(map(json.dumps, rows)))
    assert paired_agentbench(left, right) == {"wins": 1, "losses": 1, "ties": 48, "infra_excluded": 1}
    right.write_text("\n".join(map(json.dumps, rows[:-1])))
    with pytest.raises(RuntimeError, match="51 unique"):
        paired_agentbench(left, right)


def test_suite_reuses_existing_evaluators_without_sealed():
    project = Path(__file__).resolve().parents[3]
    source = (project / "scripts/train/run_qwen35_4b_opd_evaluation_suite.py").read_text()
    for script in (
        "evaluate_qwen35_4b_protocol_holdout.py",
        "run_9b_base_eval.py",
        "run_bfcl_replication.py",
        "run_tau2_replication.py",
    ):
        assert script in source
    assert re.search(r'"--max-rows",\s*"128"', source)
    assert re.search(r'"--benchmark-version",\s*"v2"', source)
    assert '"--allow-shared-gpu"' in source
    assert 'completion_lineage(marker, "opd")' in source
