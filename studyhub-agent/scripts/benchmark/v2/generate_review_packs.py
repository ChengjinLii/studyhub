#!/usr/bin/env python3
"""Create ignored, stratified semantic-review packs and a public hash manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.schema import load_jsonl, write_jsonl

SPLITS = ("regression", "development", "sealed_a", "sealed_b", "calibration_challenge")
RESEARCH_CAPABILITIES = {
    "authentic_web_research",
    "cross_chunk_synthesis",
    "long_horizon",
    "memory_rag_composition",
    "memory_web_composition",
    "memory_web_conflict_resolution",
    "multi_source_synthesis",
    "source_disambiguation_ood",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(public_root: Path, hidden_root: Path) -> list[dict[str, Any]]:
    joined = []
    for split in SPLITS:
        task_path = (
            hidden_root / f"tasks/{split}.jsonl"
            if split.startswith("sealed_")
            else public_root / f"{split}/tasks.jsonl"
        )
        tasks = {str(row["task_id"]): row for row in load_jsonl(task_path)}
        environments = {str(row["task_id"]): row for row in load_jsonl(hidden_root / f"environments/{split}.jsonl")}
        graders = {str(row["task_id"]): row for row in load_jsonl(hidden_root / f"graders/{split}.jsonl")}
        if set(tasks) != set(environments) or set(tasks) != set(graders):
            raise RuntimeError(f"review-pack bijection failed for {split}")
        for task_id, task in tasks.items():
            joined.append(
                {
                    "schema_version": "studyhub.agentbench-review-item.v2",
                    "task_id": task_id,
                    "split": split,
                    "strata": {
                        "capability": task["capability_id"],
                        "source_group": task["source_group_id"],
                        "language": task["language"],
                        "environment_origin": task["environment_origin"],
                        "semantic_cluster": task["semantic_template_cluster"],
                        "difficulty_features": task["difficulty_features"],
                    },
                    "task": task,
                    "environment": environments[task_id],
                    "grader": graders[task_id],
                    "review_form": {
                        "reviewer_type": None,
                        "verdict": None,
                        "capability_validity": None,
                        "answerability": None,
                        "path_openness": None,
                        "grader_alignment": None,
                        "source_sufficiency": None,
                        "privacy_and_policy": None,
                        "notes": None,
                    },
                }
            )
    return sorted(joined, key=lambda row: (row["split"], row["task_id"]))


def distribution(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row["strata"][key]) for row in rows).items()))


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v2")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v2/studyhub-agent-v2")
    parser.add_argument("--output-root", type=Path, default=project / "artifacts/benchmark-v2/review-packs")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/review-pack-manifest.json",
    )
    parser.add_argument(
        "--self-review",
        type=Path,
        default=project / "configs/benchmark-v2-self-review.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    all_rows = records(args.public_root, args.hidden_root)
    packs = {
        "primary-all": all_rows,
        "adversarial": [
            row
            for row in all_rows
            if row["strata"]["environment_origin"] in {"synthetic_adversarial", "synthetic_memory", "synthetic_state"}
        ],
        "research-and-synthesis": [row for row in all_rows if row["strata"]["capability"] in RESEARCH_CAPABILITIES],
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name, rows in packs.items():
        path = args.output_root / f"{name}.jsonl"
        write_jsonl(path, rows)
        entries[name] = {
            "count": len(rows),
            "sha256": sha256(path),
            "split_counts": dict(sorted(Counter(str(row["split"]) for row in rows).items())),
            "capability_counts": distribution(rows, "capability"),
            "language_counts": distribution(rows, "language"),
            "origin_counts": distribution(rows, "environment_origin"),
        }
    self_review = json.loads(args.self_review.read_text(encoding="utf-8"))
    primary_hash = entries["primary-all"]["sha256"]
    if self_review.get("primary_review_pack_sha256") != primary_hash:
        raise RuntimeError("self-review evidence is stale for the current primary review pack")
    manifest = {
        "schema_version": "studyhub.agentbench-review-pack-manifest.v2",
        "benchmark_version": "studyhub-agentbench-v2",
        "storage": "IGNORED_LOCAL_ARTIFACT",
        "contains_hidden_graders": True,
        "packs": entries,
        "review_status": {
            "self_review": self_review["status"],
            "self_reviewed_items": self_review["reviewed_items"],
            "self_review_evidence": str(args.self_review.relative_to(args.self_review.parents[1])),
            "independent_human_review": self_review["independent_human_review"],
            "external_llm_judge": self_review["external_llm_judge"],
        },
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
