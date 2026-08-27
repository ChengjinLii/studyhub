#!/usr/bin/env python3
"""Run a stratified external-judge quality review for Benchmark v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.schema import BENCHMARK_VERSION, load_jsonl

PRIMARY_PER_CAPABILITY = 6


def stable_rank(seed: int, task_id: str, lane: str) -> str:
    return hashlib.sha256(f"{seed}:{lane}:{task_id}".encode()).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_env_file(path: Path) -> dict[str, str]:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def select_rows(tasks: list[dict[str, Any]], *, seed: int) -> tuple[list[str], list[str]]:
    by_capability: dict[str, list[dict[str, Any]]] = {}
    for row in tasks:
        by_capability.setdefault(str(row["capability_id"]), []).append(row)
    primary = []
    secondary = []
    for capability_index, (_capability, rows) in enumerate(sorted(by_capability.items())):
        ordered = sorted(rows, key=lambda row: stable_rank(seed, str(row["task_id"]), "primary"))
        selected = ordered[:PRIMARY_PER_CAPABILITY]
        primary.extend(str(row["task_id"]) for row in selected)
        second_order = sorted(
            selected,
            key=lambda row: stable_rank(seed, str(row["task_id"]), "secondary"),
        )
        secondary_count = 2 if capability_index < 10 else 1
        secondary.extend(str(row["task_id"]) for row in second_order[:secondary_count])
    if len(primary) != 120 or len(secondary) != 30:
        raise RuntimeError(
            f"quality sample must contain 120 primary and 30 secondary tasks, got {len(primary)}/{len(secondary)}"
        )
    return primary, secondary


def compact_case(
    task: dict[str, Any],
    environment: dict[str, Any],
    grader: dict[str, Any],
    corpora: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    sources: dict[str, str] = {}
    corpus_id = str(environment.get("corpus_id", ""))
    sources.update({source_id: str(row.get("text", ""))[:420] for source_id, row in corpora.get(corpus_id, {}).items()})
    for field, text_field in (
        ("inline_documents", "text"),
        ("web_pages", "content"),
        ("personal_memories", "content"),
        ("collective_memories", "content"),
    ):
        for row in environment.get(field, []):
            sources[str(row["source_id"])] = str(row.get(text_field, ""))[:420]
    support_ids = sorted(
        {
            str(source_id)
            for claim in grader.get("evidence", {}).get("claims", [])
            for source_id in claim.get("support_source_ids", [])
        }
    )
    return {
        "task_id": task["task_id"],
        "capability": task["capability_id"],
        "difficulty": task["difficulty"],
        "language": task["language"],
        "horizon": task["horizon_tier"],
        "request": task["user_request"],
        "available_tools": task["available_tools"],
        "public_constraints": task["hard_constraints"],
        "objective": grader.get("objective", {}),
        "evidence_claims": grader.get("evidence", {}).get("claims", []),
        "support_excerpts": {source_id: sources.get(source_id, "<MISSING>") for source_id in support_ids},
        "failure_schedule": environment.get("failure_schedule", []),
        "private_or_stale_fixture_types": [
            str(row.get("access_scope", "free")) for row in environment.get("inline_documents", [])
        ],
        "process_policy": grader.get("process", {}),
    }


SYSTEM_PROMPT = """You are an independent benchmark quality auditor. Review each StudyHub Agent task, not the model.
The task may allow many valid tool trajectories. Do not demand a gold query, gold source order, or exact tool sequence.
Check: (1) request clarity, (2) answerability from hidden replay evidence/state, (3) grader alignment,
(4) realistic difficulty/horizon, (5) no public oracle leakage, (6) ACL/privacy safety, and (7) whether the task
actually measures the named capability rather than a superficial keyword. Return JSON only with key `reviews`.
Each review must contain task_id, verdict (PASS|MINOR|FAIL), clarity (1-5), answerability (1-5),
grader_alignment (1-5), capability_validity (1-5), path_openness (1-5), issues (list), and rationale (<=80 words).
Use FAIL for ambiguity, unreachable grading, privacy leakage, wrong capability, or a required fact absent from support.
Use MINOR only for non-blocking wording or realism concerns."""

ADVERSARIAL_PROMPT = """Independently red-team these benchmark tasks. Try to falsify the first review by finding
ambiguous goals, hidden-answer leakage, unreachable concepts, gold-path assumptions, weak capability measurement,
unsafe ACL behavior, unrealistic horizon labels, or graders that reward keyword copying. Return the same JSON schema.
Do not assume a problem exists; PASS is correct when the task remains sound under adversarial inspection."""


def call_judge(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    cases: list[dict[str, Any]],
    adversarial: bool,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = ADVERSARIAL_PROMPT if adversarial else SYSTEM_PROMPT
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps({"cases": cases}, ensure_ascii=False),
            },
        ],
        "temperature": 0.0,
        "max_tokens": 5000,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed configured endpoint
                raw = json.loads(response.read().decode())
            content = raw["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed.get("reviews"), list):
                raise ValueError("judge response has no reviews list")
            return parsed, {
                "response_id": raw.get("id"),
                "usage": raw.get("usage", {}),
                "model": raw.get("model", model),
            }
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as error:
            last_error = error
            if attempt == 3:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"judge request failed after retries: {last_error}")


def validate_reviews(
    reviews: list[dict[str, Any]],
    expected_ids: list[str],
) -> None:
    ids = [str(row.get("task_id")) for row in reviews]
    if Counter(ids) != Counter(expected_ids):
        raise RuntimeError("judge response task IDs do not match the requested batch")
    for row in reviews:
        if row.get("verdict") not in {"PASS", "MINOR", "FAIL"}:
            raise RuntimeError(f"invalid judge verdict: {row}")
        for key in ("clarity", "answerability", "grader_alignment", "capability_validity", "path_openness"):
            value = row.get(key)
            if not isinstance(value, int) or not 1 <= value <= 5:
                raise RuntimeError(f"invalid {key} score: {row}")


def run_review(args: argparse.Namespace) -> dict[str, Any]:
    tasks = load_jsonl(args.public_root / "development/tasks.jsonl")
    environments = {str(row["task_id"]): row for row in load_jsonl(args.hidden_root / "environments/development.jsonl")}
    graders = {str(row["task_id"]): row for row in load_jsonl(args.hidden_root / "graders/development.jsonl")}
    corpora = {}
    for path in (args.hidden_root / "corpora").glob("*.jsonl"):
        corpora[path.stem] = {str(row["source_id"]): row for row in load_jsonl(path)}
    primary_ids, secondary_ids = select_rows(tasks, seed=args.seed)
    by_id = {str(row["task_id"]): row for row in tasks}
    cases = {
        task_id: compact_case(by_id[task_id], environments[task_id], graders[task_id], corpora)
        for task_id in primary_ids
    }
    secrets = load_env_file(args.env_file)
    api_key = os.getenv("XIAOMI_API_KEY") or secrets.get("XIAOMI_API_KEY", "")
    base_url = os.getenv("XIAOMI_BASE_URL") or secrets.get("XIAOMI_BASE_URL", "")
    if not api_key or not base_url:
        raise RuntimeError("XIAOMI_API_KEY and XIAOMI_BASE_URL must be configured")

    args.output_root.mkdir(parents=True, exist_ok=True)
    primary_reviews = []
    secondary_reviews = []
    call_metadata = []
    for lane, ids, adversarial, output in (
        ("primary", primary_ids, False, primary_reviews),
        ("secondary", secondary_ids, True, secondary_reviews),
    ):
        for start in range(0, len(ids), args.batch_size):
            batch_ids = ids[start : start + args.batch_size]
            parsed, metadata = call_judge(
                endpoint=base_url,
                api_key=api_key,
                model=args.model,
                cases=[cases[task_id] for task_id in batch_ids],
                adversarial=adversarial,
                timeout=args.timeout,
            )
            validate_reviews(parsed["reviews"], batch_ids)
            output.extend(parsed["reviews"])
            call_metadata.append({"lane": lane, "batch": start // args.batch_size, **metadata})
            print(f"{lane}: reviewed {min(start + args.batch_size, len(ids))}/{len(ids)}", flush=True)

    primary_by_id = {str(row["task_id"]): row for row in primary_reviews}
    disagreements = []
    for row in secondary_reviews:
        task_id = str(row["task_id"])
        first = primary_by_id[task_id]
        if first["verdict"] != row["verdict"]:
            disagreements.append(
                {
                    "task_id": task_id,
                    "primary": first["verdict"],
                    "secondary": row["verdict"],
                }
            )
    review_rows = [{"lane": "primary", **row} for row in primary_reviews] + [
        {"lane": "secondary", **row} for row in secondary_reviews
    ]
    review_path = args.output_root / "judge-reviews.jsonl"
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in review_rows),
        encoding="utf-8",
    )
    verdict_counts = {
        "primary": dict(Counter(str(row["verdict"]) for row in primary_reviews)),
        "secondary": dict(Counter(str(row["verdict"]) for row in secondary_reviews)),
    }
    blocking = [row for row in review_rows if row["verdict"] == "FAIL"]
    summary = {
        "schema_version": "studyhub.agentbench-quality-review.v1",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "reviewer": {
            "provider": "xiaomi-openai-compatible",
            "requested_model": args.model,
            "temperature": 0.0,
            "prompt_sha256": hashlib.sha256((SYSTEM_PROMPT + ADVERSARIAL_PROMPT).encode()).hexdigest(),
        },
        "primary_tasks": len(primary_reviews),
        "double_reviewed_tasks": len(secondary_reviews),
        "verdict_counts": verdict_counts,
        "blocking_failures": len(blocking),
        "disagreements": disagreements,
        "review_jsonl_sha256": sha256(review_path),
        "calls": call_metadata,
        "freeze_eligible": not blocking,
    }
    summary_path = args.output_root / "quality-review-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_summary = {
        key: summary[key]
        for key in (
            "schema_version",
            "benchmark_version",
            "generated_at",
            "reviewer",
            "primary_tasks",
            "double_reviewed_tasks",
            "verdict_counts",
            "blocking_failures",
            "disagreements",
            "review_jsonl_sha256",
            "freeze_eligible",
        )
    }
    public_path = args.public_root / "quality-review-summary.json"
    public_path.write_text(json.dumps(public_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--public-root",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v1",
    )
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1/quality",
    )
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".hermes/.env")
    parser.add_argument("--model", default="mimo-v2.5-pro")
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    summary = run_review(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["freeze_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
