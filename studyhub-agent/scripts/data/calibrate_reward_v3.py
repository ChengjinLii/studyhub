#!/usr/bin/env python3
"""Replay controlled cases and measure Reward v3 calibration behavior."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scipy.stats import kendalltau, spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from training.rl.environment_v3 import TrainingTaskEnvironmentV3  # noqa: E402
from training.rl.reward_v3 import SCORED_STATUS, evaluate_reward_v3  # noqa: E402


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _without_citations(value: str) -> str:
    return re.sub(r"\s*\[[^\[\]\s]{2,240}\]", "", value).strip()


def _first_expected(verifier: dict[str, Any]) -> str:
    groups = verifier.get("objective", {}).get("acceptable_answers", [])
    for group in groups:
        for value in group:
            if str(value).strip():
                return str(value).strip()
    return ""


def _mutated_plan(
    case: dict[str, Any],
    witness: dict[str, Any],
    verifier: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    execution = case["execution"]
    actions = list(witness.get("actions", []))
    answer = str(witness.get("final_answer", ""))
    objective = dict(verifier.get("objective", {}))
    mode = str(objective.get("mode", "facts"))
    claims = list(verifier.get("claims", []))
    if execution == "canonical":
        return actions, answer
    if execution == "alternative":
        return list(witness.get("alternative_actions", [])), str(witness.get("alternative_final_answer", ""))
    if execution == "adversarial_mutation":
        if claims:
            return actions, f"{answer} [calibration-fabricated-source]"
        return [
            *actions,
            {"name": "__forbidden_calibration_tool__", "arguments": {}},
        ], answer
    if execution == "boundary_mutation":
        if mode in {"state", "facts_and_state", "successful_tool_outcome"}:
            return actions[:-1], answer
        if claims:
            return actions, _without_citations(answer)
        if mode == "abstain":
            forbidden = list(objective.get("forbidden_specifics", []))
            specific = str(forbidden[0]) if forbidden else "2026-09-18"
            return actions, f"证据不足，但具体值可能是 {specific}。"
        return actions, "回答尚不完整，未给出结论。"
    if execution == "outcome_without_evidence":
        if mode == "abstain":
            forbidden = list(objective.get("forbidden_specifics", []))
            specific = str(forbidden[0]) if forbidden else "2026-09-18"
            return [], f"无法确认，但我断言具体值是 {specific}。"
        if claims or mode in {"state", "facts_and_state", "successful_tool_outcome"}:
            return [], _without_citations(answer)
        expected = _first_expected(verifier)
        if re.fullmatch(r"[A-Da-d]", expected):
            return [], "候选项包括 A、B、C、D，尚未作答。"
        return [], f"题干中出现“{expected}”，但未给出结论。"
    raise ValueError(f"unsupported calibration execution: {execution}")


async def _evaluate(
    *,
    dataset: Path,
    task_id: str,
    actions: list[dict[str, Any]],
    final_answer: str,
    verifier: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    environment = TrainingTaskEnvironmentV3.from_root(dataset, task_id)
    for action in actions:
        await environment.execute(str(action["name"]), dict(action.get("arguments", {})))
    result = evaluate_reward_v3(
        final_answer=final_answer,
        trace=environment.trace_dict(),
        final_state=environment.state_snapshot(),
        verifier=verifier,
    )
    return result.to_dict(), environment.trace_dict()


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 6)


def _p05(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(0.05 * len(ordered)) - 1)], 6)


async def calibrate(
    *,
    dataset: Path,
    suite: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verifiers = {row["task_id"]: row for row in read_jsonl(dataset / "verifiers/protocol_holdout.jsonl")}
    witnesses = {row["task_id"]: row for row in read_jsonl(dataset / "audit/witnesses-protocol_holdout.jsonl")}
    cases = read_jsonl(suite / "cases.jsonl")
    rows = []
    for index, case in enumerate(cases, start=1):
        task_id = str(case["task_id"])
        verifier = verifiers[task_id]
        witness = witnesses[task_id]
        actions, final_answer = _mutated_plan(case, witness, verifier)
        result, trace = await _evaluate(
            dataset=dataset,
            task_id=task_id,
            actions=actions,
            final_answer=final_answer,
            verifier=verifier,
        )
        reference_reward = None
        if case["case_type"] == "alternative_valid_path":
            reference, _ = await _evaluate(
                dataset=dataset,
                task_id=task_id,
                actions=list(witness["actions"]),
                final_answer=str(witness["final_answer"]),
                verifier=verifier,
            )
            reference_reward = reference["total"]
        predicted_accept = bool(result["strict_success"])
        rows.append(
            {
                **case,
                "reward_status": result["status"],
                "reward": result["total"],
                "strict_success": predicted_accept,
                "label_correct": predicted_accept == bool(case["expected_accept"]),
                "hard_gate": result["hard_gate_triggered"],
                "hard_gate_reasons": result["hard_gate_reasons"],
                "objective": result["objective_end_state"],
                "grounding": result["grounding"],
                "semantic": result["semantic_rubric"],
                "process": result["process_quality"],
                "tool_calls": len(trace.get("tool_calls", [])),
                "policy_errors": list(trace.get("policy_errors", [])),
                "final_answer_sha256": sha256_text(final_answer),
                "reference_canonical_reward": reference_reward,
            }
        )
        if index % 100 == 0:
            print(f"calibrated: {index}/{len(cases)}", file=sys.stderr)

    expected = [float(row["expected_quality"]) for row in rows]
    rewards = [float(row["reward"]) for row in rows]
    spearman = float(spearmanr(expected, rewards).statistic)
    kendall = float(kendalltau(expected, rewards).statistic)
    rejects = [row for row in rows if not row["expected_accept"]]
    accepts = [row for row in rows if row["expected_accept"]]
    false_positives = [row for row in rejects if row["strict_success"]]
    false_negatives = [row for row in accepts if not row["strict_success"]]

    base_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["case_type"] != "alternative_valid_path":
            base_rows[row["task_id"]].append(row)
    pair_total = 0
    pair_correct = 0
    for group in base_rows.values():
        for left in group:
            for right in group:
                if left["expected_quality"] <= right["expected_quality"]:
                    continue
                pair_total += 1
                pair_correct += left["reward"] > right["reward"]

    named_pairs = (
        ("normal", "boundary"),
        ("normal", "reward_hacking"),
        ("normal", "adversarial"),
        ("boundary", "reward_hacking"),
        ("boundary", "adversarial"),
        ("reward_hacking", "adversarial"),
    )
    paired_margins = {}
    for better, worse in named_pairs:
        margins = []
        for group in base_rows.values():
            indexed = {row["case_type"]: row for row in group}
            margins.append(float(indexed[better]["reward"]) - float(indexed[worse]["reward"]))
        paired_margins[f"{better}_vs_{worse}"] = {
            "strict_win_rate": _rate(sum(margin > 0 for margin in margins), len(margins)),
            "non_inversion_rate": _rate(sum(margin >= 0 for margin in margins), len(margins)),
            "minimum": round(min(margins), 6),
            "p05": _p05(margins),
            "mean": round(sum(margins) / len(margins), 6),
        }

    alternative_rows = [row for row in rows if row["case_type"] == "alternative_valid_path"]
    alternative_deltas = [
        abs(float(row["reward"]) - float(row["reference_canonical_reward"])) for row in alternative_rows
    ]
    adversarial = [row for row in rows if row["case_type"] == "adversarial"]
    by_type = {}
    for case_type in sorted({row["case_type"] for row in rows}):
        subset = [row for row in rows if row["case_type"] == case_type]
        by_type[case_type] = {
            "count": len(subset),
            "strict_accept_rate": _rate(sum(row["strict_success"] for row in subset), len(subset)),
            "mean_reward": round(sum(row["reward"] for row in subset) / len(subset), 6),
            "hard_gate_rate": _rate(sum(row["hard_gate"] for row in subset), len(subset)),
        }
    by_family = {}
    for family in sorted({row["family"] for row in rows}):
        subset = [row for row in rows if row["family"] == family]
        by_family[family] = {
            "count": len(subset),
            "label_accuracy": _rate(sum(row["label_correct"] for row in subset), len(subset)),
            "false_positives": sum(not row["expected_accept"] and row["strict_success"] for row in subset),
            "false_negatives": sum(row["expected_accept"] and not row["strict_success"] for row in subset),
        }

    metrics = {
        "cases": len(rows),
        "scored": sum(row["reward_status"] == SCORED_STATUS for row in rows),
        "label_accuracy": _rate(sum(row["label_correct"] for row in rows), len(rows)),
        "false_positives": len(false_positives),
        "false_positive_rate": _rate(len(false_positives), len(rejects)),
        "false_negatives": len(false_negatives),
        "false_negative_rate": _rate(len(false_negatives), len(accepts)),
        "pairwise_accuracy": _rate(pair_correct, pair_total),
        "pairwise_comparisons": pair_total,
        "paired_margins": paired_margins,
        "spearman": round(spearman, 6),
        "kendall_tau_b": round(kendall, 6),
        "adversarial_hard_gate_rate": _rate(sum(row["hard_gate"] for row in adversarial), len(adversarial)),
        "alternative_strict_pass_rate": _rate(
            sum(row["strict_success"] for row in alternative_rows), len(alternative_rows)
        ),
        "alternative_mean_abs_reward_delta": round(sum(alternative_deltas) / len(alternative_deltas), 6),
        "alternative_p95_abs_reward_delta": _p95(alternative_deltas),
        "positive_reward_but_expected_reject": sum(row["reward"] > 0 and not row["expected_accept"] for row in rows),
        "by_case_type": by_type,
        "by_family": by_family,
        "hard_gate_reason_counts": dict(
            sorted(Counter(reason for row in rows for reason in row["hard_gate_reasons"]).items())
        ),
    }
    return rows, metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/agent_rl_v3",
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/reward_v3_calibration",
    )
    parser.add_argument("--allow-failed-gates", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows, metrics = asyncio.run(calibrate(dataset=args.dataset, suite=args.suite))
    gates = {
        "all_cases_scored": metrics["scored"] == metrics["cases"],
        "label_accuracy_gte_0_98": metrics["label_accuracy"] >= 0.98,
        "false_positive_rate_lte_0_01": metrics["false_positive_rate"] <= 0.01,
        "false_negative_rate_lte_0_01": metrics["false_negative_rate"] <= 0.01,
        "pairwise_accuracy_gte_0_95": metrics["pairwise_accuracy"] >= 0.95,
        "spearman_gte_0_85": metrics["spearman"] >= 0.85,
        "kendall_gte_0_75": metrics["kendall_tau_b"] >= 0.75,
        "adversarial_hard_gate_gte_0_99": metrics["adversarial_hard_gate_rate"] >= 0.99,
        "alternative_strict_pass_gte_0_99": metrics["alternative_strict_pass_rate"] >= 0.99,
        "alternative_p95_delta_lte_0_05": metrics["alternative_p95_abs_reward_delta"] <= 0.05,
        "normal_beats_reward_hacking": metrics["paired_margins"]["normal_vs_reward_hacking"]["strict_win_rate"] == 1.0,
        "normal_reward_hacking_p05_margin_gte_0_20": metrics["paired_margins"]["normal_vs_reward_hacking"]["p05"]
        >= 0.20,
        "no_pairwise_reward_inversions": all(
            row["non_inversion_rate"] == 1.0 for row in metrics["paired_margins"].values()
        ),
    }
    report = {
        "schema_version": "studyhub.reward-v3-calibration-report.v1",
        "reward_version": "studyhub.reward-v3.0.0",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "scope": "controlled_programmatic_calibration_not_human_or_teacher_review",
        "training_started": False,
        "sealed_files_read": False,
        "metrics": metrics,
        "gates": gates,
        "suite_manifest_sha256": sha256(args.suite / "manifest.json"),
        "dataset_manifest_sha256": sha256(args.dataset / "manifest.json"),
    }
    write_jsonl(args.suite / "results.jsonl", rows)
    write_json(args.suite / "report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS" and not args.allow_failed_gates:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
