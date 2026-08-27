#!/usr/bin/env python3
"""Produce a source-level audit of immutable runtime-SFT-v3.0."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scripts.data.select_runtime_sft_v3 import (
    candidate_prompt_hash,
    public_benchmark_prompt_hashes,
    semantic_template,
    sha256,
)

CITATION = re.compile(r"\[(?:wiki|paper|studyhub-material|web-material):[^]]+]", re.IGNORECASE)
CUSTOM_SOURCES = {
    "studyhub_metadata_replay",
    "studyhub_memory_replay",
    "studyhub_acl_recovery",
    "studyhub_web_fallback",
    "studyhub_state_tools",
}
QUALITY_CLASS = {
    "teacher_verified_complete": "teacher",
    "teacher_repaired_complete": "teacher_repaired",
    "expert_recorded_complete": "expert_recorded",
    "expert_complete": "expert_recorded",
    "oracle_verified_complete": "oracle",
    "oracle_derived_expert_complete": "oracle",
    "deterministic_fixture_complete": "fixture",
    "expert_action_synthetic_observation": "synthetic_observation",
    "expert_action_only": "action_only",
}


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def final_answer(row: dict[str, Any]) -> str:
    return next(
        (
            str(message.get("content", ""))
            for message in reversed(row.get("messages", []))
            if message.get("role") == "assistant" and not message.get("tool_calls")
        ),
        "",
    )


def tool_signature(row: dict[str, Any]) -> str:
    names = [
        str(call.get("function", {}).get("name", ""))
        for message in row.get("messages", [])
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    ]
    return "→".join(name for name in names if name) or "DIRECT"


def language(row: dict[str, Any]) -> str:
    explicit = str(row.get("language", "")).casefold()
    if explicit in {"zh", "en"}:
        return explicit
    prompt = next(
        (str(message.get("content", "")) for message in row.get("messages", []) if message.get("role") == "user"),
        "",
    )
    return "zh" if re.search(r"[\u3400-\u9fff]", prompt) else "en"


def observation_origin(row: dict[str, Any]) -> str:
    quality = str(row.get("quality_tier", ""))
    if quality in {"teacher_verified_complete", "teacher_repaired_complete"}:
        return "teacher_in_real_environment"
    if quality == "oracle_derived_expert_complete":
        return "oracle_derived_replay"
    if quality == "deterministic_fixture_complete":
        return "deterministic_fixture"
    if quality == "expert_action_synthetic_observation":
        return "synthetic_observation"
    if quality == "expert_action_only":
        return "no_complete_observation_and_final"
    if not any(message.get("role") == "tool" for message in row.get("messages", [])):
        return "no_tool_observation"
    return "open_dataset_recorded_or_converted"


def _counter(value: Counter[Any]) -> dict[str, int]:
    return {str(key): count for key, count in sorted(value.items(), key=lambda item: str(item[0]))}


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected", type=Path, default=project / "datasets/interim/runtime_sft_v3/selected.jsonl")
    parser.add_argument(
        "--token-manifest",
        type=Path,
        default=project / "datasets/processed/runtime_sft_v3_qwen35_9b/manifest.json",
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/manifest.json",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=project / "docs/training/evidence/runtime-sft-v3-source-audit.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=project / "docs/training/RUNTIME_SFT_V3_SOURCE_AUDIT.md",
    )
    return parser.parse_args()


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(__file__).resolve().parents[2]
    token_manifest = json.loads(args.token_manifest.read_text(encoding="utf-8"))
    benchmark_manifest = json.loads(args.benchmark_manifest.read_text(encoding="utf-8"))
    benchmark_hashes, benchmark_tasks = public_benchmark_prompt_hashes(project, benchmark_manifest)
    source: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "rows": 0,
            "split": Counter(),
            "trajectory_status": Counter(),
            "quality_tiers": Counter(),
            "quality_classes": Counter(),
            "runtime_native": 0,
            "groups": Counter(),
            "template_clusters": Counter(),
            "tool_sequences": Counter(),
            "final_signatures": Counter(),
            "capabilities": Counter(),
            "languages": Counter(),
            "citation_rows": 0,
            "observation_origin": Counter(),
        }
    )
    prompt_overlap = 0
    total = 0
    with args.selected.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            name = str(row["source_dataset"])
            item = source[name]
            item["rows"] += 1
            item["split"][str(row.get("split"))] += 1
            item["trajectory_status"][str(row.get("trajectory_status"))] += 1
            quality = str(row.get("quality_tier"))
            item["quality_tiers"][quality] += 1
            item["quality_classes"][QUALITY_CLASS.get(quality, "unclassified")] += 1
            item["runtime_native"] += int(bool(row.get("runtime_native")))
            item["groups"][str(row.get("group_id"))] += 1
            item["template_clusters"][semantic_template(row)] += 1
            item["tool_sequences"][tool_signature(row)] += 1
            answer = final_answer(row)
            if answer:
                signature = hashlib.sha256(normalized(answer).encode()).hexdigest()[:20]
                item["final_signatures"][signature] += 1
                item["citation_rows"] += int(bool(CITATION.search(answer)))
            for capability in row.get("capability_tags", []):
                item["capabilities"][str(capability)] += 1
            item["languages"][language(row)] += 1
            item["observation_origin"][observation_origin(row)] += 1
            prompt_overlap += int(candidate_prompt_hash(row) in benchmark_hashes)
            total += 1

    source_rows: dict[str, Any] = {}
    for name, item in sorted(source.items()):
        rows = int(item["rows"])
        group_sizes = list(item["groups"].values())
        cluster_sizes = list(item["template_clusters"].values())
        tool_sizes = list(item["tool_sequences"].values())
        final_sizes = list(item["final_signatures"].values())
        all_tokens = int(token_manifest.get("source_all_tokens", {}).get(name, 0))
        loss_tokens = int(token_manifest.get("source_loss_tokens", {}).get(name, 0))
        source_rows[name] = {
            "rows": rows,
            "row_share": round(rows / max(total, 1), 6),
            "complete_rows": int(item["trajectory_status"].get("complete", 0)),
            "action_only_rows": int(item["trajectory_status"].get("action_only", 0)),
            "runtime_native_rows": int(item["runtime_native"]),
            "runtime_native_share": round(item["runtime_native"] / max(rows, 1), 6),
            "quality_tiers": _counter(item["quality_tiers"]),
            "quality_classes": _counter(item["quality_classes"]),
            "observation_origin": _counter(item["observation_origin"]),
            "total_tokens": all_tokens,
            "assistant_loss_tokens": loss_tokens,
            "assistant_fraction": round(loss_tokens / max(all_tokens, 1), 6),
            "split": _counter(item["split"]),
            "unique_groups": len(group_sizes),
            "rows_per_group": {
                "p50": percentile(group_sizes, 0.50),
                "p90": percentile(group_sizes, 0.90),
                "max": max(group_sizes, default=0),
            },
            "template_clusters": len(cluster_sizes),
            "largest_template_cluster_share": round(max(cluster_sizes, default=0) / max(rows, 1), 6),
            "tool_sequence_signatures": len(tool_sizes),
            "largest_tool_sequence_share": round(max(tool_sizes, default=0) / max(rows, 1), 6),
            "final_answer_signatures": len(final_sizes),
            "largest_final_answer_share": round(max(final_sizes, default=0) / max(rows, 1), 6),
            "capability_tags": _counter(item["capabilities"]),
            "language": _counter(item["languages"]),
            "citation_rows": int(item["citation_rows"]),
            "citation_rate": round(item["citation_rows"] / max(rows, 1), 6),
        }

    action_only = {
        name: row["action_only_rows"] for name, row in source_rows.items() if row["action_only_rows"]
    }
    fixture = {
        name: row["quality_classes"].get("fixture", 0)
        for name, row in source_rows.items()
        if row["quality_classes"].get("fixture", 0)
    }
    custom_group_max = {
        name: row["rows_per_group"]["max"] for name, row in source_rows.items() if name in CUSTOM_SOURCES
    }
    failures: list[str] = []
    if total != 48_500:
        failures.append(f"row_count:{total}")
    if sum(action_only.values()) != 6_158:
        failures.append(f"action_only_count:{sum(action_only.values())}")
    if sum(fixture.values()) != 20_000:
        failures.append(f"fixture_count:{sum(fixture.values())}")
    if prompt_overlap:
        failures.append(f"benchmark_prompt_overlap:{prompt_overlap}")
    return {
        "schema_version": "studyhub.runtime-sft-v3-source-audit.v1",
        "status": "PASS" if not failures else "FAIL",
        "dataset_release": "runtime-SFT-v3.0",
        "immutable_selected_sha256": sha256(args.selected),
        "token_manifest_sha256": sha256(args.token_manifest),
        "benchmark_manifest_sha256": sha256(args.benchmark_manifest),
        "benchmark_tasks_checked": benchmark_tasks,
        "benchmark_splits_checked": ["regression", "development", "calibration_challenge"],
        "sealed_task_files_read": False,
        "sealed_overlap_recheck": "INHERITED_FROM_FROZEN_V3_SOURCE_LOCK_NOT_RECOMPUTED",
        "benchmark_prompt_overlap": prompt_overlap,
        "rows": total,
        "total_tokens": int(token_manifest["all_tokens"]),
        "assistant_loss_tokens": int(token_manifest["loss_tokens"]),
        "assistant_fraction": round(token_manifest["loss_tokens"] / token_manifest["all_tokens"], 6),
        "action_only": {"total": sum(action_only.values()), "by_source": action_only},
        "deterministic_fixture": {"total": sum(fixture.values()), "by_source": fixture},
        "teacher_verified_rows": sum(row["quality_classes"].get("teacher", 0) for row in source_rows.values()),
        "custom_source_group_max": custom_group_max,
        "sources": source_rows,
        "failures": failures,
        "interpretation": {
            "runtime_native_is_teacher": False,
            "template_cluster_is_semantic_embedding_cluster": False,
            "quality_labels_describe_provenance": True,
        },
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Runtime-SFT-v3.0 Source Audit",
        "",
        f"Status: `{audit['status']}`",
        f"Selected SHA-256: `{audit['immutable_selected_sha256']}`",
        f"Benchmark prompt overlap: `{audit['benchmark_prompt_overlap']}` / `{audit['benchmark_tasks_checked']}`",
        "",
        "## Dataset Summary",
        "",
        "| Item | Value |",
        "| --- | ---: |",
        f"| Rows | {audit['rows']:,} |",
        f"| Total tokens | {audit['total_tokens']:,} |",
        f"| Assistant-loss tokens | {audit['assistant_loss_tokens']:,} |",
        f"| Assistant fraction | {audit['assistant_fraction']:.2%} |",
        f"| Action-only rows | {audit['action_only']['total']:,} |",
        f"| Deterministic fixture rows | {audit['deterministic_fixture']['total']:,} |",
        f"| Teacher-verified rows | {audit['teacher_verified_rows']:,} |",
        "",
        "The 6,158 action-only rows are ToolACE 5,753 and Hermes Function Calling 405. The 20,000 deterministic fixtures are StudyHub metadata 6,000, memory 4,000, ACL 4,000, Web 3,000, and state tools 3,000. `runtime_native` means runtime-schema compatible; it does not mean a teacher model autonomously executed the trajectory.",
        "",
        "## Source Detail",
        "",
        "| Source | Rows | Complete | Action-only | Runtime-native | Total tokens | Assistant tokens | Assistant % | Groups | Group p90/max | Template clusters | Largest template | Tool paths | Largest path |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in audit["sources"].items():
        lines.append(
            f"| {name} | {row['rows']:,} | {row['complete_rows']:,} | {row['action_only_rows']:,} | "
            f"{row['runtime_native_share']:.1%} | {row['total_tokens']:,} | {row['assistant_loss_tokens']:,} | "
            f"{row['assistant_fraction']:.1%} | {row['unique_groups']:,} | "
            f"{row['rows_per_group']['p90']}/{row['rows_per_group']['max']} | {row['template_clusters']:,} | "
            f"{row['largest_template_cluster_share']:.1%} | {row['tool_sequence_signatures']:,} | "
            f"{row['largest_tool_sequence_share']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Provenance and Concentration",
            "",
        ]
    )
    for name, row in audit["sources"].items():
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Quality tiers: `{json.dumps(row['quality_tiers'], ensure_ascii=False, sort_keys=True)}`",
                f"- Observation origin: `{json.dumps(row['observation_origin'], ensure_ascii=False, sort_keys=True)}`",
                f"- Rows/group p50, p90, max: `{row['rows_per_group']['p50']}`, `{row['rows_per_group']['p90']}`, `{row['rows_per_group']['max']}`",
                f"- Final-answer signatures: `{row['final_answer_signatures']}`; largest exact normalized answer share: `{row['largest_final_answer_share']:.2%}`",
                f"- Language: `{json.dumps(row['language'], ensure_ascii=False, sort_keys=True)}`; citation rate: `{row['citation_rate']:.2%}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "The current v3.0 release is a valid frozen cold-start baseline, not a teacher-policy dataset. Oracle 2Wiki/QASPER rows teach successful evidence paths; deterministic StudyHub rows teach schemas and reproducible outcomes; action-only rows do not teach observation-following or final answers. The per-source template metric is a deterministic template proxy, not an embedding-based semantic cluster. These distinctions drive the separate v3.1 teacher candidate and prevent fixtures from being promoted to teacher quality.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    audit = build_audit(args)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(audit), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "json": str(args.json_output), "markdown": str(args.markdown_output)}, ensure_ascii=False))
    return 0 if audit["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
