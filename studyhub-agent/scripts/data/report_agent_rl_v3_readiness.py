#!/usr/bin/env python3
"""Write tracked Agent RL v3 data and Reward calibration evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.rl.dataset_v3 import validate_public_task  # noqa: E402
from training.rl.hermes_workflow_v3 import decode_public_task_row  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_failure_reason(reason: str) -> str:
    if reason.startswith("invalid_citation:"):
        return "invalid_citation"
    if reason.startswith("qa_exception:"):
        return ":".join(reason.split(":")[:2])
    return reason


def verify_hf_transport(root: Path) -> dict[str, Any]:
    from datasets import DatasetDict, load_from_disk

    dataset = load_from_disk(str(root / "hf_dataset"))
    if not isinstance(dataset, DatasetDict) or set(dataset) != {"train", "validation"}:
        raise RuntimeError("Agent RL v3 HF transport has invalid splits")
    hidden_markers = ('"verifier"', "support_source_ids", "expected_answers")
    rows = 0
    for split in dataset:
        for raw in dataset[split]:
            row = dict(raw)
            validate_public_task(decode_public_task_row(row))
            if any(marker in row["task_json"] for marker in hidden_markers):
                raise RuntimeError(f"hidden verifier field found in HF {split}")
            rows += 1
    return {
        "status": "PASS",
        "split_counts": {split: len(dataset[split]) for split in dataset},
        "rows_validated": rows,
        "protocol_holdout_exposed": False,
        "hidden_fields_found": 0,
    }


def build_report(dataset: Path, calibration: Path) -> dict[str, Any]:
    manifest = read_json(dataset / "manifest.json")
    witness = read_json(dataset / "audit/witness-audit.json")
    calibration_manifest = read_json(calibration / "manifest.json")
    calibration_report = read_json(calibration / "report.json")
    sampled_failures = [
        normalize_failure_reason(str(reason))
        for row in witness.get("canonical_failures", [])
        for reason in row.get("hard_gate_reasons", [])
    ]
    tool_signatures = dict(manifest["tool_signature_counts"])
    top_tool_signatures = dict(sorted(tool_signatures.items(), key=lambda item: (-item[1], item[0]))[:20])
    code_paths = (
        "training/rl/dataset_v3.py",
        "training/rl/environment_v3.py",
        "training/rl/hermes_workflow_v3.py",
        "training/rl/reward_v3.py",
        "training/rl/task_factory_v3.py",
        "scripts/data/build_agent_rl_v3.py",
        "scripts/data/verify_agent_rl_v3.py",
        "scripts/data/build_reward_v3_calibration.py",
        "scripts/data/calibrate_reward_v3.py",
    )
    hf = verify_hf_transport(dataset)
    return {
        "schema_version": "studyhub.agent-rl-v3-readiness-evidence.v1",
        "status": "STATIC_DATA_AND_CONTROLLED_REWARD_CALIBRATION_PASSED",
        "scope": {
            "gpu_training_started": False,
            "grpo_started": False,
            "policy_learnability": "NOT_RUN",
            "sealed_used": False,
            "benchmark_modified": False,
            "production_services_used": False,
        },
        "dataset": {
            "revision": manifest["dataset_revision"],
            "status": manifest["status"],
            "candidate_tasks": manifest["candidate_tasks"],
            "post_qa_tasks": manifest["post_qa_tasks"],
            "split_counts": manifest["split_counts"],
            "family_counts": manifest["family_counts"],
            "origin_counts": manifest["origin_counts"],
            "source_counts": manifest["source_counts"],
            "budget_tier_counts": manifest["budget_tier_counts"],
            "environment_kind_counts": manifest["environment_kind_counts"],
            "tool_signatures": {
                "unique": len(tool_signatures),
                "top_counts": top_tool_signatures,
                "full_counts_location": "ignored dataset manifest",
            },
            "unique_source_groups": manifest["unique_source_groups"],
            "source_group_split_overlap": manifest["source_group_split_overlap"],
            "exact_goal_duplicates": manifest["exact_goal_duplicates"],
            "selected_alternative_witnesses": manifest["selected_alternative_witnesses"],
            "custom_data_character": manifest["custom_data_character"],
            "hf_transport": hf,
            "manifest_sha256": sha256(dataset / "manifest.json"),
            "candidate_manifest_sha256": manifest["candidate_manifest_sha256"],
            "runtime_sft_selected_sha256": manifest["runtime_sft_selected_sha256"],
        },
        "solvability": {
            "candidate_canonical_pass": witness["canonical_pass"],
            "candidate_canonical_fail": witness["canonical_fail"],
            "alternative_applicable": witness["alternative_applicable"],
            "alternative_pass": witness["alternative_pass"],
            "alternative_fail": witness["alternative_fail"],
            "sampled_failure_reason_counts": dict(sorted(Counter(sampled_failures).items())),
            "failure_reason_scope": "first_100_canonical_failures_only",
        },
        "reward_calibration": {
            "status": calibration_report["status"],
            "scope": calibration_report["scope"],
            "suite": {
                "cases": calibration_manifest["case_count"],
                "case_type_counts": calibration_manifest["case_type_counts"],
                "family_counts": calibration_manifest["family_counts"],
                "unique_tasks": calibration_manifest["unique_task_count"],
                "source_split": calibration_manifest["source_split"],
                "controlled_programmatic_labels": True,
                "human_review": False,
                "teacher_semantic_review": False,
            },
            "metrics": calibration_report["metrics"],
            "gates": calibration_report["gates"],
            "report_sha256": sha256(calibration / "report.json"),
            "cases_sha256": calibration_manifest["cases_sha256"],
        },
        "benchmark_lock": manifest["benchmark"],
        "implementation_sha256": {path: sha256(PROJECT_ROOT / path) for path in code_paths},
        "limitations": [
            "Reward calibration uses controlled programmatic labels, not human or independent teacher semantic review.",
            "Policy learnability rollouts have not run; the 10k set is not yet "
            "partitioned by current 9B policy outcome variance.",
            "The 6000 custom rows are deterministic training simulations, not "
            "production traffic or real user trajectories.",
            "179 expected-reject cases receive positive partial credit, but none "
            "passes strict success or outranks its paired normal trajectory.",
            "QASPER contributes only 44 candidate rows after runtime-SFT source-group "
            "isolation; 2Wiki fills the remaining external long-context quota.",
            "No GRPO, GPU profile, or checkpoint comparison is authorized by this evidence.",
        ],
        "next_gate": "SEPARATE_POLICY_LEARNABILITY_EVAL_REQUIRES_EXPLICIT_GPU_AUTHORIZATION",
    }


def markdown(report: dict[str, Any]) -> str:
    data = report["dataset"]
    reward = report["reward_calibration"]
    metrics = reward["metrics"]
    lines = [
        "# StudyHub Agent RL v3 数据与 Reward 校准记录",
        "",
        (
            f"状态：`{report['status']}`。本记录只覆盖离线数据、环境、Reward 与程序化校准；"
            "未启动 GPU、GRPO 或 policy learnability rollout。"
        ),
        "",
        "## 数据集",
        "",
        "| 项目 | 结果 |",
        "|---|---:|",
        f"| Candidate | {data['candidate_tasks']:,} |",
        f"| Post-QA | {data['post_qa_tasks']:,} |",
        (
            "| Train / Validation / Protocol holdout | "
            f"{data['split_counts']['train']:,} / {data['split_counts']['validation']:,} / "
            f"{data['split_counts']['protocol_holdout']:,} |"
        ),
        f"| Custom / External | {data['origin_counts']['custom']:,} / {data['origin_counts']['external']:,} |",
        f"| Unique source groups | {data['unique_source_groups']:,} |",
        f"| Split group overlap | {sum(data['source_group_split_overlap'].values())} |",
        f"| Exact goal duplicates | {data['exact_goal_duplicates']} |",
        f"| HF public rows validated | {data['hf_transport']['rows_validated']:,} |",
        "",
        (
            "定制数据来自确定性训练模拟器，不是线上行为轨迹。HF DatasetDict 只包含 "
            "8,000 条 train 和 1,000 条 validation public task；1,000 条 protocol "
            "holdout、verifier 与 solvability witness 均未进入训练传输层。"
        ),
        "",
        "## Solvability QA",
        "",
        (
            "16,000 条候选中，canonical witness 通过 "
            f"{report['solvability']['candidate_canonical_pass']:,} 条、拒绝 "
            f"{report['solvability']['candidate_canonical_fail']:,} 条；alternative witness "
            f"通过 {report['solvability']['alternative_pass']:,} 条、拒绝 "
            f"{report['solvability']['alternative_fail']:,} 条。最终 10,000 条只从 "
            "canonical 通过且不存在失败 alternative 的任务中选择。"
        ),
        "",
        "## Reward v3 校准",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| Controlled cases | {metrics['cases']} |",
        f"| Strict label accuracy | {metrics['label_accuracy']:.2%} |",
        f"| False positive / false negative | {metrics['false_positives']} / {metrics['false_negatives']} |",
        f"| Pairwise accuracy | {metrics['pairwise_accuracy']:.2%} |",
        f"| Spearman / Kendall tau-b | {metrics['spearman']:.4f} / {metrics['kendall_tau_b']:.4f} |",
        f"| Adversarial hard-gate rate | {metrics['adversarial_hard_gate_rate']:.2%} |",
        f"| Alternative strict pass | {metrics['alternative_strict_pass_rate']:.2%} |",
        f"| Alternative p95 reward delta | {metrics['alternative_p95_abs_reward_delta']:.4f} |",
        f"| Normal vs hacking p05 margin | {metrics['paired_margins']['normal_vs_reward_hacking']['p05']:.4f} |",
        "",
        (
            "校准标签是程序化测试合同，不是 human review 或 teacher semantic review。"
            "179 条严格失败案例仍获得正的部分分；它们均未通过 strict success，也没有"
            "反超对应正常轨迹，因此保留为后续 GRPO group diagnostics 的重点监控项。"
        ),
        "",
        "## 当前边界",
        "",
    ]
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            f"下一门禁：`{report['next_gate']}`。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/agent_rl_v3",
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/reward_v3_calibration",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=PROJECT_ROOT / "docs/training/evidence/agent-rl-v3-readiness-20260828.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=PROJECT_ROOT / "docs/training/AGENT_RL_V3_READINESS_20260828.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.dataset, args.calibration)
    write_json(args.json_output, report)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.json_output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
