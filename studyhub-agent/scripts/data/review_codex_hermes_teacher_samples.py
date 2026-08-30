#!/usr/bin/env python3
"""Run a bounded Codex self-review over accepted and rejected teacher runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from training.teacher.providers import CODEX_DISABLED_FEATURES  # noqa: E402

REVIEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [
                "UPHOLD_ACCEPT",
                "FLAG_FALSE_POSITIVE",
                "UPHOLD_REJECT",
                "FLAG_FALSE_NEGATIVE",
                "INDETERMINATE",
            ],
        },
        "reason_code": {"type": "string", "maxLength": 80},
        "brief_explanation": {"type": "string", "maxLength": 500},
    },
    "required": ["verdict", "reason_code", "brief_explanation"],
}

REVIEW_DEVELOPER_INSTRUCTIONS = """This is a bounded data-quality review, not a coding task.
Use no tool, shell, filesystem, browser, plan, or hidden reasoning output. Review only the JSON
package in stdin. Return exactly one JSON object matching the supplied schema. The explanation
must be brief and must not include chain-of-thought."""

VERDICTS_BY_DECISION = {
    "ACCEPTED": {"UPHOLD_ACCEPT", "FLAG_FALSE_POSITIVE", "INDETERMINATE"},
    "REJECTED": {"UPHOLD_REJECT", "FLAG_FALSE_NEGATIVE", "INDETERMINATE"},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_rank(seed: int, label: str, identifier: str) -> str:
    return hashlib.sha256(f"{seed}:{label}:{identifier}".encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for value in [json.loads(line)]
        if isinstance(value, dict)
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def stratified_sample(
    rows: list[dict[str, Any]],
    count: int,
    *,
    seed: int,
    label: str,
    family_key: str,
    id_key: str,
) -> list[dict[str, Any]]:
    if count > len(rows):
        raise RuntimeError(f"requested {count} rows from a population of {len(rows)}")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(family_key, "unknown"))].append(row)
    for family, values in groups.items():
        values.sort(key=lambda row: stable_rank(seed, f"{label}:{family}", str(row[id_key])))
    selected: list[dict[str, Any]] = []
    families = sorted(groups)
    while len(selected) < count:
        progressed = False
        for family in families:
            if groups[family]:
                selected.append(groups[family].pop(0))
                progressed = True
                if len(selected) == count:
                    break
        if not progressed:
            raise RuntimeError("stratified sampler exhausted unexpectedly")
    return selected


def load_task_map(root: Path) -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in read_jsonl(root / "task_specs.jsonl")}


def review_prompt(package: dict[str, Any]) -> str:
    return """Review whether the deterministic verifier decision is semantically justified.

For an ACCEPTED item, use FLAG_FALSE_POSITIVE only when the visible trajectory does not actually
satisfy the task, grounding, ACL, state, or final-answer contract. For a REJECTED item, use
FLAG_FALSE_NEGATIVE only when the visible trajectory clearly satisfies the contract despite the
listed failures. Otherwise uphold the decision. INDETERMINATE is allowed when the package lacks
enough evidence. Do not propose a new trajectory and do not expose chain-of-thought.

Review package:
""" + json.dumps(package, ensure_ascii=False, sort_keys=True)


def invoke_codex(
    item: dict[str, Any],
    *,
    model: str,
    command: str,
    timeout: int,
) -> dict[str, Any]:
    started_id = str(item["review_id"])
    with tempfile.TemporaryDirectory(prefix="studyhub-teacher-review-") as directory:
        root = Path(directory)
        schema = root / "review-schema.json"
        output = root / "review.json"
        schema.write_text(json.dumps(REVIEW_SCHEMA, sort_keys=True), encoding="utf-8")
        argv = [
            command,
            "--ask-for-approval",
            "never",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--config",
            'web_search="disabled"',
            "--config",
            f"developer_instructions={json.dumps(REVIEW_DEVELOPER_INSTRUCTIONS)}",
        ]
        for feature in CODEX_DISABLED_FEATURES:
            argv.extend(["--disable", feature])
        argv.extend(
            [
                "--model",
                model,
                "--cd",
                str(root),
                "--output-schema",
                str(schema),
                "--output-last-message",
                str(output),
                "--json",
                "-",
            ]
        )
        try:
            process = subprocess.run(
                argv,
                input=review_prompt(item["package"]),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except subprocess.TimeoutExpired:
            return {
                "review_id": started_id,
                "status": "PROVIDER_ERROR",
                "error_code": "codex_timeout",
                "decision": item["decision"],
                "run_id": item["run_id"],
                "family": item["family"],
            }
        event = {
            "exit_code": process.returncode,
            "stdout_sha256": hashlib.sha256(process.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(process.stderr.encode()).hexdigest(),
        }
        if process.returncode != 0 or not output.is_file():
            return {
                "review_id": started_id,
                "status": "PROVIDER_ERROR",
                "decision": item["decision"],
                "run_id": item["run_id"],
                "family": item["family"],
                "provider_event": event,
            }
        review = read_json(output)
        verdict = str(review.get("verdict", ""))
        if verdict not in VERDICTS_BY_DECISION[item["decision"]]:
            return {
                "review_id": started_id,
                "status": "PROVIDER_ERROR",
                "error_code": "invalid_verdict_for_decision",
                "decision": item["decision"],
                "run_id": item["run_id"],
                "family": item["family"],
                "provider_event": event,
            }
        return {
            "review_id": started_id,
            "status": "COMPLETE",
            "decision": item["decision"],
            "run_id": item["run_id"],
            "family": item["family"],
            "review": review,
            "provider_event": event,
        }


def build_items(
    roots: list[Path], accepted_count: int, rejected_count: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted_population: list[dict[str, Any]] = []
    rejected_population: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    task_maps: dict[Path, dict[str, dict[str, Any]]] = {}
    for root in sorted(path.resolve() for path in roots):
        manifest = read_json(root / "manifest.json")
        if manifest.get("status") != "PASS":
            raise RuntimeError(f"teacher batch is not PASS: {root}")
        accepted_path = root / "accepted.jsonl"
        rejected_path = root / "rejected.jsonl"
        if manifest.get("accepted_sha256") != sha256(accepted_path):
            raise RuntimeError(f"accepted hash drift: {root}")
        if manifest.get("rejected_sha256") != sha256(rejected_path):
            raise RuntimeError(f"rejected hash drift: {root}")
        accepted_population.extend(
            {
                "root": root,
                "row": row,
                "family": str(row["task_family"]),
                "identifier": str(row["source_id"]),
            }
            for row in read_jsonl(accepted_path)
        )
        rejected_population.extend(
            {
                "root": root,
                "row": row,
                "family": str(row["family"]),
                "identifier": str(row["run_id"]),
            }
            for row in read_jsonl(rejected_path)
        )
        task_maps[root] = load_task_map(root)
        lineage.append(
            {
                "root": str(root),
                "manifest_sha256": sha256(root / "manifest.json"),
                "accepted_sha256": sha256(accepted_path),
                "rejected_sha256": sha256(rejected_path),
            }
        )
    accepted = stratified_sample(
        accepted_population,
        accepted_count,
        seed=seed,
        label="accepted",
        family_key="family",
        id_key="identifier",
    )
    rejected = stratified_sample(
        rejected_population,
        rejected_count,
        seed=seed,
        label="rejected",
        family_key="family",
        id_key="identifier",
    )

    def hydrate(entry: dict[str, Any], decision: str) -> dict[str, Any]:
        root = Path(entry["root"])
        row = entry["row"]
        run_id = str(row["source_id"] if decision == "ACCEPTED" else row["run_id"])
        raw = read_json(root / "raw_runs" / f"{run_id}.json")
        task = task_maps[root][str(raw["task_id"])]
        verifier = read_json(root / "verifiers" / f"{raw['task_id']}.json")
        family = str(task["family"])
        review_id = hashlib.sha256(f"{decision}:{root}:{run_id}".encode()).hexdigest()[:24]
        package = {
            "review_type": "codex_self_review_not_human_review",
            "original_decision": decision,
            "task": task,
            "verifier": verifier,
            "messages": raw["messages"],
            "controller": raw.get("controller"),
            "existing_diagnostics": (row.get("verification") if decision == "ACCEPTED" else row),
        }
        return {
            "review_id": review_id,
            "decision": decision,
            "run_id": run_id,
            "family": family,
            "package": package,
        }

    items = [hydrate(entry, "ACCEPTED") for entry in accepted]
    items.extend(hydrate(entry, "REJECTED") for entry in rejected)
    return items, lineage


def summarize(reviews: list[dict[str, Any]], lineage: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(str(row.get("review", {}).get("verdict", row.get("status", "UNKNOWN"))) for row in reviews)
    return {
        "schema_version": "studyhub.codex-hermes-teacher-self-review.v1",
        "status": "COMPLETE" if all(row.get("status") == "COMPLETE" for row in reviews) else "INCOMPLETE",
        "review_type": "codex_self_review",
        "independent_human_review": False,
        "teacher_interface": "codex-cli",
        "reviewed_rows": len(reviews),
        "accepted_reviewed": sum(row.get("decision") == "ACCEPTED" for row in reviews),
        "rejected_reviewed": sum(row.get("decision") == "REJECTED" for row in reviews),
        "verdict_counts": dict(sorted(verdicts.items())),
        "lineage": lineage,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", action="append", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--accepted", type=int, default=50)
    parser.add_argument("--rejected", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if os.environ.get("STUDYHUB_ALLOW_TEACHER_SELF_REVIEW") != "YES":
        raise RuntimeError("set STUDYHUB_ALLOW_TEACHER_SELF_REVIEW=YES")
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("codex CLI is unavailable")
    items, lineage = build_items(args.input_root, args.accepted, args.rejected, args.seed)
    args.output_root.mkdir(parents=True, exist_ok=True)
    sample = {"items": items, "lineage": lineage}
    sample_path = args.output_root / "sample.json"
    if sample_path.is_file() and read_json(sample_path) != sample:
        raise RuntimeError(f"existing review sample drifted: {sample_path}")
    if not sample_path.is_file():
        write_json(sample_path, sample)

    reviews: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for item in items:
        existing_path = args.output_root / "reviews" / f"{item['review_id']}.json"
        existing = read_json(existing_path) if existing_path.is_file() else None
        if existing and existing.get("status") == "COMPLETE":
            reviews.append(existing)
        else:
            pending.append(item)

    if reviews:
        print(f"resumed {len(reviews)} complete reviews; pending {len(pending)}", flush=True)
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(
                invoke_codex,
                item,
                model=args.model,
                command=executable,
                timeout=args.timeout,
            ): item
            for item in pending
        }
        for future in as_completed(futures):
            result = future.result()
            attempts_root = args.output_root / "attempts" / result["review_id"]
            attempt_index = len(list(attempts_root.glob("attempt-*.json"))) + 1
            write_json(attempts_root / f"attempt-{attempt_index:03d}.json", result)
            write_json(args.output_root / "reviews" / f"{result['review_id']}.json", result)
            reviews.append(result)
            print(
                f"reviewed {len(reviews)}/{len(items)} "
                f"{result['decision']} {result.get('review', {}).get('verdict', result['status'])}",
                flush=True,
            )
    reviews.sort(key=lambda row: row["review_id"])
    manifest = summarize(reviews, lineage)
    manifest.update(
        {
            "seed": args.seed,
            "model": args.model,
            "requested_accepted": args.accepted,
            "requested_rejected": args.rejected,
            "sample_sha256": sha256(sample_path),
        }
    )
    write_json(args.output_root / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "COMPLETE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
