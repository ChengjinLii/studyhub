#!/usr/bin/env python3
"""Compare SFT assistant-loss exposure with public Development capability mix."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_LANES = {
    "studyhub_2wiki_replay": "rag_evidence",
    "studyhub_qasper_replay": "rag_evidence",
    "hermes_function_calling": "function_state",
    "toolace": "function_state",
    "coig_exam": "direct_tutoring",
}

CAPABILITY_LANES = {
    "factual_passage_retrieval": "rag_evidence",
    "cross_chunk_synthesis": "rag_evidence",
    "query_reformulation": "rag_evidence",
    "insufficient_evidence": "rag_evidence",
    "multi_source_synthesis": "rag_evidence",
    "authentic_web_research": "web_research",
    "memory_absence": "memory",
    "memory_collective_conflict": "memory",
    "memory_collective_low_confidence": "memory",
    "memory_cross_user_privacy": "memory",
    "memory_current_conflict": "memory",
    "memory_incomplete_abstention": "memory",
    "memory_irrelevant_tool_abstention": "memory",
    "memory_rag_composition": "memory",
    "memory_scope_resolution": "memory",
    "memory_selection": "memory",
    "memory_temporal_change": "memory",
    "memory_user_correction": "memory",
    "memory_web_composition": "memory",
    "state_function_calling": "function_state",
    "state_multistep_postcondition": "function_state",
    "permission_avoidance": "recovery_acl",
    "permission_recovery": "recovery_acl",
    "tool_failure_recovery": "recovery_acl",
    "direct_answer_tool_relevance": "direct_tutoring",
    "stop_cost_control": "direct_tutoring",
    "long_horizon": "long_horizon",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def load_public_development(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("split") != "development":
            raise RuntimeError(f"non-Development row at {path}:{line_number}: {row.get('split')}")
        rows.append(row)
    if not rows:
        raise RuntimeError("public Development split is empty")
    return rows


def aggregate_training_lanes(source_shares: dict[str, Any]) -> dict[str, float]:
    unknown = sorted(set(source_shares) - set(SOURCE_LANES))
    if unknown:
        raise RuntimeError(f"unclassified training sources: {unknown}")
    lanes: defaultdict[str, float] = defaultdict(float)
    for source, share in source_shares.items():
        lanes[SOURCE_LANES[source]] += float(share)
    return dict(lanes)


def aggregate_benchmark_lanes(
    rows: list[dict[str, Any]],
) -> tuple[Counter[str], Counter[str]]:
    capability_counts = Counter(str(row["capability_id"]) for row in rows)
    unknown = sorted(set(capability_counts) - set(CAPABILITY_LANES))
    if unknown:
        raise RuntimeError(f"unclassified Development capabilities: {unknown}")
    lane_counts: Counter[str] = Counter()
    for capability, count in capability_counts.items():
        lane_counts[CAPABILITY_LANES[capability]] += count
    return capability_counts, lane_counts


def build_audit(project: Path) -> dict[str, Any]:
    data_card_path = project / "configs/program-v3/open-only-sft-v1-data-card.json"
    benchmark_manifest_path = project / "benchmarks/studyhub-agent-v2/manifest.json"
    development_path = project / "benchmarks/studyhub-agent-v2/development/tasks.jsonl"
    data_card = load_json(data_card_path)
    source_shares = data_card["selection"]["train_source_assistant_loss_shares"]
    training_lanes = aggregate_training_lanes(source_shares)
    development = load_public_development(development_path)
    capability_counts, benchmark_lanes = aggregate_benchmark_lanes(development)
    benchmark_total = len(development)

    lane_names = sorted(set(training_lanes) | set(benchmark_lanes))
    lane_matrix = []
    for lane in lane_names:
        train_share = training_lanes.get(lane, 0.0)
        benchmark_count = benchmark_lanes.get(lane, 0)
        benchmark_share = benchmark_count / benchmark_total
        lane_matrix.append(
            {
                "lane": lane,
                "training_assistant_loss_share": round(train_share, 6),
                "development_task_count": benchmark_count,
                "development_task_share": round(benchmark_share, 6),
                "share_delta_percentage_points": round((train_share - benchmark_share) * 100, 3),
            }
        )

    source_matrix = []
    for source, share in sorted(source_shares.items()):
        lane = SOURCE_LANES[source]
        development_share = benchmark_lanes.get(lane, 0) / benchmark_total
        source_matrix.append(
            {
                "source": source,
                "assistant_loss_share": float(share),
                "coarse_support_lane": lane,
                "development_lane_share": round(development_share, 6),
                "mapping_semantics": "COARSE_EXPOSURE_PROXY_NOT_CAPABILITY_EQUIVALENCE",
            }
        )

    benchmark_hash = sha256(benchmark_manifest_path)
    expected_hash = data_card["isolation"]["benchmark_manifest_sha256"]
    if benchmark_hash != expected_hash:
        raise RuntimeError("Benchmark manifest drift against Open-Only data card")
    if abs(sum(float(value) for value in source_shares.values()) - 1.0) > 1e-5:
        raise RuntimeError("training assistant-loss shares do not sum to one")
    if sum(benchmark_lanes.values()) != benchmark_total:
        raise RuntimeError("Development lane classification is incomplete")

    return {
        "schema_version": "studyhub.sft-benchmark-alignment-audit.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS_WITH_ALIGNMENT_BIAS_DISCLOSED",
        "scope": {
            "training_dataset": "open-only-sft-v1-qwen35-9b",
            "training_measure": "train_assistant_loss_token_share",
            "benchmark_split": "PUBLIC_DEVELOPMENT_ONLY",
            "sealed_accessed": False,
            "mapping_semantics": "COARSE_EXPOSURE_PROXY_NOT_SEMANTIC_CAPABILITY_EQUIVALENCE",
        },
        "training_sources": source_matrix,
        "development_capability_counts": dict(sorted(capability_counts.items())),
        "lane_matrix": lane_matrix,
        "findings": {
            "rag_training_share": round(training_lanes.get("rag_evidence", 0.0), 6),
            "rag_development_share": round(benchmark_lanes.get("rag_evidence", 0) / benchmark_total, 6),
            "uncovered_development_lanes": sorted(
                lane for lane, count in benchmark_lanes.items() if count > 0 and training_lanes.get(lane, 0.0) == 0.0
            ),
            "claim_boundary": (
                "A positive internal RAG direction cannot be generalized to Web, Memory, "
                "Recovery/ACL, or long-horizon Agent capability without direct and external evidence."
            ),
        },
        "inputs": {
            "data_card": {
                "path": str(data_card_path.relative_to(project)),
                "sha256": sha256(data_card_path),
            },
            "benchmark_manifest": {
                "path": str(benchmark_manifest_path.relative_to(project)),
                "sha256": benchmark_hash,
            },
            "public_development": {
                "path": str(development_path.relative_to(project)),
                "sha256": sha256(development_path),
                "rows": benchmark_total,
            },
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_audit(args.project_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps({"status": payload["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
