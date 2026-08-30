#!/usr/bin/env python3
"""Lock fresh BFCL and tau2 IDs without copying task or oracle content."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

BFCL_FILES = {
    "simple_python": "BFCL_v4_simple_python.json",
    "parallel": "BFCL_v4_parallel.json",
    "multiple": "BFCL_v4_multiple.json",
    "irrelevance": "BFCL_v4_irrelevance.json",
    "multi_turn_base": "BFCL_v4_multi_turn_base.json",
    "multi_turn_miss_func": "BFCL_v4_multi_turn_miss_func.json",
    "multi_turn_miss_param": "BFCL_v4_multi_turn_miss_param.json",
}
TAU_DOMAINS = ("airline", "retail", "telecom")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        value = json.loads(text)
        return value if isinstance(value, list) else [value]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def select_ids(ids: list[str], excluded: set[str], seed: int, lane: str, count: int) -> list[str]:
    candidates = sorted(set(ids) - excluded)
    ranked = sorted(candidates, key=lambda value: hashlib.sha256(f"{seed}:{lane}:{value}".encode()).hexdigest())
    if len(ranked) < count:
        raise RuntimeError(f"{lane}: need {count} fresh IDs, found {len(ranked)}")
    return ranked[:count]


def previous_bfcl_ids(result_root: Path) -> dict[str, set[str]]:
    previous: dict[str, set[str]] = {}
    for category, filename in BFCL_FILES.items():
        paths = list(result_root.rglob(filename.replace(".json", "_result.json")))
        if not paths:
            raise RuntimeError(f"missing previous BFCL result for {category}")
        previous[category] = {str(row["id"]) for row in load_json_records(paths[0])}
    return previous


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--bfcl-source", type=Path, required=True)
    parser.add_argument("--bfcl-previous-results", type=Path, required=True)
    parser.add_argument("--tau2-source", type=Path, required=True)
    parser.add_argument("--previous-evidence", type=Path, required=True)
    parser.add_argument("--bfcl-output", type=Path, default=project / "configs/eval/bfcl-4b-pipeline-holdout-v1.json")
    parser.add_argument("--tau2-output", type=Path, default=project / "configs/eval/tau2-4b-pipeline-holdout-v1.json")
    parser.add_argument("--evidence-dir", type=Path, default=project / "docs/benchmark/evidence")
    args = parser.parse_args()

    previous_evidence = json.loads(args.previous_evidence.read_text(encoding="utf-8"))
    previous_bfcl = previous_bfcl_ids(args.bfcl_previous_results)
    bfcl_ids: dict[str, list[str]] = {}
    bfcl_hashes: dict[str, str] = {}
    for category, filename in BFCL_FILES.items():
        path = args.bfcl_source / "berkeley-function-call-leaderboard/bfcl_eval/data" / filename
        rows = load_json_records(path)
        bfcl_ids[category] = select_ids(
            [str(row["id"]) for row in rows], previous_bfcl[category], args.seed, f"bfcl:{category}", 10
        )
        bfcl_hashes[category] = sha256(path)

    previous_tau = {domain: set(previous_evidence["tau2"]["task_ids"][domain]) for domain in TAU_DOMAINS}
    tau_ids: dict[str, list[str]] = {}
    tau_hashes: dict[str, str] = {}
    for domain in TAU_DOMAINS:
        path = args.tau2_source / f"data/tau2/domains/{domain}/tasks.json"
        rows = load_json_records(path)
        tau_ids[domain] = select_ids(
            [str(row["id"]) for row in rows], previous_tau[domain], args.seed, f"tau2:{domain}", 5
        )
        tau_hashes[domain] = sha256(path)

    bfcl = {
        "schema_version": "studyhub.bfcl-4b-pipeline-holdout.v1",
        "status": "LOCKED_UNEXPOSED",
        "seed": args.seed,
        "selection": "sha256_order_after_excluding_20260830_replication_ids",
        "tasks_per_category": 10,
        "task_ids": bfcl_ids,
        "source_file_sha256": bfcl_hashes,
        "training_access": False,
        "opened_for_model_selection": False,
    }
    tau = {
        "schema_version": "studyhub.tau2-4b-pipeline-holdout.v1",
        "status": "LOCKED_UNEXPOSED",
        "seed": args.seed,
        "selection": "sha256_order_after_excluding_20260830_replication_ids",
        "tasks_per_domain": 5,
        "task_ids": tau_ids,
        "source_file_sha256": tau_hashes,
        "training_access": False,
        "opened_for_model_selection": False,
    }
    args.bfcl_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    args.bfcl_output.write_text(json.dumps(bfcl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.tau2_output.write_text(json.dumps(tau, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name, config, output in (
        ("bfcl", bfcl, args.bfcl_output),
        ("tau2", tau, args.tau2_output),
    ):
        evidence = {
            "schema_version": f"studyhub.{name}-4b-pipeline-holdout-lock-evidence.v1",
            "status": "PASS",
            "config": str(output.resolve()),
            "config_sha256": sha256(output),
            "selected_id_set_sha256": hashlib.sha256(
                json.dumps(config["task_ids"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "previous_ids_excluded": True,
            "task_content_copied": False,
            "training_access": False,
        }
        (args.evidence_dir / f"{name}-4b-pipeline-holdout-lock.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"bfcl": bfcl, "tau2": tau}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
