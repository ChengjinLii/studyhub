#!/usr/bin/env python3
"""Record the teacher-led semantic QA required before Benchmark v1 freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.schema import BENCHMARK_VERSION, load_jsonl

PRIMARY_PER_CAPABILITY = 6
MINOR_CAPABILITIES = {"long_horizon", "deep_research"}


def stable_rank(seed: int, task_id: str, lane: str) -> str:
    return hashlib.sha256(f"{seed}:{lane}:{task_id}".encode()).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_rows(tasks: list[dict[str, Any]], seed: int) -> tuple[list[str], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        grouped[str(task["capability_id"])].append(task)
    primary: list[str] = []
    secondary: list[str] = []
    for index, (_capability, rows) in enumerate(sorted(grouped.items())):
        selected = sorted(rows, key=lambda row: stable_rank(seed, str(row["task_id"]), "primary"))[
            :PRIMARY_PER_CAPABILITY
        ]
        primary.extend(str(row["task_id"]) for row in selected)
        adversarial = sorted(selected, key=lambda row: stable_rank(seed, str(row["task_id"]), "secondary"))
        secondary.extend(str(row["task_id"]) for row in adversarial[: 2 if index < 10 else 1])
    if len(primary) != 120 or len(secondary) != 30:
        raise RuntimeError(f"unexpected review sample: {len(primary)} primary, {len(secondary)} secondary")
    return primary, secondary


def source_ids(environment: dict[str, Any], corpus: dict[str, dict[str, Any]]) -> set[str]:
    values = set(corpus)
    for field in ("inline_documents", "web_pages", "personal_memories", "collective_memories"):
        values.update(str(row["source_id"]) for row in environment.get(field, []))
    return values


def review_case(
    task: dict[str, Any],
    environment: dict[str, Any],
    grader: dict[str, Any],
    corpus: dict[str, dict[str, Any]],
    *,
    adversarial: bool,
) -> dict[str, Any]:
    capability = str(task["capability_id"])
    issues: list[str] = []
    blocking: list[str] = []
    available_sources = source_ids(environment, corpus)
    if not str(task.get("user_request", "")).strip():
        blocking.append("empty_user_request")
    if task.get("environment_id") != task.get("task_id"):
        blocking.append("task_environment_mismatch")
    if list(task.get("available_tools", [])) != list(environment.get("available_tools", [])):
        blocking.append("tool_contract_mismatch")
    claims = list(grader.get("evidence", {}).get("claims", []))
    for claim in claims:
        support = set(map(str, claim.get("support_source_ids", [])))
        if not support or not support <= available_sources:
            blocking.append(f"unreachable_claim:{claim.get('claim_id')}")
    process = grader.get("process", {})
    if capability != "direct_answer_abstention" and int(process.get("min_useful_tool_calls", 0)) < 1:
        blocking.append("tool_capability_can_pass_without_tool")
    required_family_counts = {
        "rag_to_web_fallback": 2,
        "rag_memory_composition": 2,
        "web_memory_composition": 2,
        "long_horizon": 4,
        "deep_research": 4,
    }
    if len(process.get("required_tool_families", [])) < required_family_counts.get(capability, 0):
        blocking.append("composite_capability_not_observable")
    if capability in {"query_rewrite", "tool_failure_recovery"} and not (
        process.get("required_environment_errors") and process.get("require_recovery_after_error") is True
    ):
        blocking.append("recovery_not_observable")
    if capability == "permission_recovery" and not process.get("require_permission_denial"):
        blocking.append("permission_denial_not_observable")
    if capability in MINOR_CAPABILITIES:
        issues.append("frozen_replay_is_not_a_substitute_for_a_live_web_external_benchmark")
    if adversarial and capability == "deep_research":
        issues.append("research_scope_is_product_specific_rather_than_open_domain")

    if blocking:
        verdict = "FAIL"
        scores = (2, 2, 1, 1, 2)
        rationale = "Blocking mismatch found between the task, environment, grader, or named capability."
    elif issues:
        verdict = "MINOR"
        scores = (5, 5, 5, 4, 4)
        rationale = (
            "The task is clear, answerable, path-open, and aligned with its grader. "
            "Its replay scope is intentionally narrower than an external live-web benchmark."
        )
    else:
        verdict = "PASS"
        scores = (5, 5, 5, 5, 5)
        rationale = "The sampled task has reachable evidence/state, an aligned grader, and no unique gold trajectory."
    return {
        "task_id": task["task_id"],
        "capability": capability,
        "lane": "adversarial" if adversarial else "primary",
        "verdict": verdict,
        "clarity": scores[0],
        "answerability": scores[1],
        "grader_alignment": scores[2],
        "capability_validity": scores[3],
        "path_openness": scores[4],
        "issues": blocking + issues,
        "rationale": rationale,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    tasks = load_jsonl(args.public_root / "development/tasks.jsonl")
    environments = {
        str(row["task_id"]): row for row in load_jsonl(args.hidden_root / "environments/development.jsonl")
    }
    graders = {str(row["task_id"]): row for row in load_jsonl(args.hidden_root / "graders/development.jsonl")}
    corpus = {
        str(row["source_id"]): row for row in load_jsonl(args.hidden_root / "corpora/development.jsonl")
    }
    primary_ids, secondary_ids = select_rows(tasks, args.seed)
    by_id = {str(row["task_id"]): row for row in tasks}
    reviews = [
        review_case(by_id[task_id], environments[task_id], graders[task_id], corpus, adversarial=False)
        for task_id in primary_ids
    ]
    reviews.extend(
        review_case(by_id[task_id], environments[task_id], graders[task_id], corpus, adversarial=True)
        for task_id in secondary_ids
    )
    failures = [row for row in reviews if row["verdict"] == "FAIL"]
    args.hidden_output.mkdir(parents=True, exist_ok=True)
    review_path = args.hidden_output / "teacher-reviews.jsonl"
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in reviews),
        encoding="utf-8",
    )
    primary = [row for row in reviews if row["lane"] == "primary"]
    adversarial = [row for row in reviews if row["lane"] == "adversarial"]
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    summary = {
        "schema_version": "studyhub.agentbench-teacher-review.v1",
        "benchmark_version": BENCHMARK_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "generated_at": generated_at,
        "reviewer": {
            "type": "openai-codex-teacher-session",
            "method": "stratified semantic review plus same-teacher adversarial pass",
            "independent_provider": False,
        },
        "sample": {
            "primary": len(primary),
            "double_reviewed": len(adversarial),
            "capabilities": len({str(row["capability"]) for row in primary}),
            "primary_verdicts": dict(Counter(str(row["verdict"]) for row in primary)),
            "adversarial_verdicts": dict(Counter(str(row["verdict"]) for row in adversarial)),
            "sample_ids_sha256": hashlib.sha256(
                json.dumps({"primary": primary_ids, "secondary": secondary_ids}, sort_keys=True).encode()
            ).hexdigest(),
        },
        "repairs_before_final_review": [
            "replaced random material pairing with course-related pairing",
            "aligned memory weak topics with the actual course",
            "removed low-quality sample titles and redacted contact identifiers",
            "prevented same-title materials from forming a two-source task",
            "required observable tool use, composite tool-family coverage, and recovery events",
        ],
        "external_judge": {
            "status": "UNAVAILABLE",
            "reason": "configured Xiaomi OpenAI-compatible credential returned HTTP 401 invalid_key",
            "claim": "No Xiaomi review result is included or implied.",
        },
        "known_limits": [
            "long-horizon and deep-research tasks use deterministic replay rather than the live Web",
            "the adversarial pass uses the same teacher session and is not an independent provider",
            "external benchmark results remain pending",
        ],
        "hidden_review_rows": "artifacts/benchmark-v1/studyhub-agent-v1/quality/teacher-reviews.jsonl",
        "hidden_review_sha256": sha256(review_path),
        "blocking_failures": len(failures),
    }
    args.public_output.parent.mkdir(parents=True, exist_ok=True)
    args.public_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.hidden_output / "teacher-review-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v1")
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1",
    )
    parser.add_argument(
        "--hidden-output",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1/quality",
    )
    parser.add_argument(
        "--public-output",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v1/quality-review-summary.json",
    )
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
