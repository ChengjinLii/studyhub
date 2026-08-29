#!/usr/bin/env python3
"""Fail-closed audit and data-card generator for Open-Agentic SFT v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for import_root in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.data.select_runtime_sft_v3 import (  # noqa: E402
    candidate_prompt_hash,
    near_signature,
    public_benchmark_prompt_hashes,
    sha256,
)
from scripts.data.tokenize_runtime_sft_v3 import assistant_loss_mask  # noqa: E402
from studyhub_agent.trajectory.runtime_sft import validate_runtime_trajectory  # noqa: E402

_CJK = re.compile(r"[\u3400-\u9fff]")
FORBIDDEN_PREFIXES = (
    "studyhub_metadata",
    "studyhub_memory",
    "studyhub_acl",
    "studyhub_web",
    "studyhub_state",
    "studyhub_teacher",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def user_text(row: dict[str, Any]) -> str:
    return next(
        (str(message.get("content", "")) for message in row.get("messages", []) if message.get("role") == "user"),
        "",
    )


def source_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["source_dataset"])].append(row)
    result = {}
    for source, source_rows in sorted(grouped.items()):
        groups = Counter(str(row["group_id"]) for row in source_rows)
        paths = Counter(str(row["tool_path_signature"]) for row in source_rows)
        abstract_paths = Counter(str(row["abstract_tool_path"]) for row in source_rows)
        assistant_tokens = sum(int(row["tokenization"]["assistant_loss_tokens"]) for row in source_rows)
        total_tokens = sum(int(row["tokenization"]["total_tokens"]) for row in source_rows)
        result[source] = {
            "source_family": source_rows[0]["source_family"],
            "rows": len(source_rows),
            "total_tokens": total_tokens,
            "assistant_loss_tokens": assistant_tokens,
            "assistant_fraction": round(assistant_tokens / total_tokens, 8),
            "unique_groups": len(groups),
            "rows_per_group": {
                "p50": percentile(list(groups.values()), 0.50),
                "p90": percentile(list(groups.values()), 0.90),
                "max": max(groups.values()),
            },
            "quality_tiers": dict(sorted(Counter(str(row["policy_quality_tier"]) for row in source_rows).items())),
            "behavior_tags": dict(
                sorted(Counter(tag for row in source_rows for tag in map(str, row.get("behavior_tags", []))).items())
            ),
            "tool_path_signatures": len(paths),
            "largest_exact_tool_path_row_share": round(max(paths.values()) / len(source_rows), 8),
            "abstract_tool_paths": dict(sorted(abstract_paths.items())),
            "tool_calls_per_trajectory": {
                "p50": percentile([int(row["tool_call_count"]) for row in source_rows], 0.50),
                "p90": percentile([int(row["tool_call_count"]) for row in source_rows], 0.90),
                "max": max(int(row["tool_call_count"]) for row in source_rows),
            },
            "language": dict(
                sorted(Counter("zh" if _CJK.search(user_text(row)) else "en" for row in source_rows).items())
            ),
            "licenses": sorted({str(row["provenance"].get("license", "")) for row in source_rows}),
            "revisions": sorted({str(row["provenance"].get("revision", "")) for row in source_rows}),
            "observation_origin": dict(
                sorted(Counter(str(row.get("environment_origin", "")) for row in source_rows).items())
            ),
        }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--program",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-agentic-sft-v2.json",
    )
    parser.add_argument(
        "--selected",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.jsonl",
    )
    parser.add_argument(
        "--processed",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/open_agentic_sft_v2_qwen35_9b",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_ROOT.parent / "models/P1/Qwen3.5-9B",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-data-audit.json",
    )
    parser.add_argument(
        "--data-card",
        type=Path,
        default=PROJECT_ROOT / "docs/training/OPEN_AGENTIC_SFT_V2_DATA_CARD.md",
    )
    parser.add_argument(
        "--semantic-evidence",
        type=Path,
        default=PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-semantic-dedup.json",
    )
    parser.add_argument("--skip-mask-recompute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from transformers import AutoTokenizer

    from datasets import load_from_disk

    program = load_json(args.program)
    selected_manifest_path = args.selected.with_suffix(".manifest.json")
    selected_manifest = load_json(selected_manifest_path)
    token_manifest_path = args.processed / "manifest.json"
    token_manifest = load_json(token_manifest_path)
    semantic_evidence = load_json(args.semantic_evidence)
    if selected_manifest["output_sha256"] != sha256(args.selected):
        raise RuntimeError("selected dataset hash drift")
    if selected_manifest["tokenized_manifest_sha256"] != sha256(token_manifest_path):
        raise RuntimeError("tokenized manifest hash drift")
    if (
        semantic_evidence.get("status") != "PASS"
        or semantic_evidence.get("lineage", {}).get("input_sha256") != sha256(args.selected)
        or int(semantic_evidence.get("hard_cross_group_pairs", -1)) != 0
    ):
        raise RuntimeError("selected semantic dedup evidence is not passing or has drifted")

    benchmark_path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark = load_json(benchmark_path)
    if sha256(benchmark_path) != program["benchmark_lock"]["manifest_sha256"]:
        raise RuntimeError("Benchmark v2 manifest drift")
    benchmark_hashes, benchmark_rows = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark)

    rows: list[dict[str, Any]] = []
    ids: set[str] = set()
    exact: set[str] = set()
    near_groups: dict[str, str] = {}
    groups_by_split: dict[str, set[str]] = defaultdict(set)
    benchmark_overlap = []
    failures = []
    with args.selected.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            row_failures = validate_runtime_trajectory(row)
            if row_failures:
                failures.append({"id": row.get("id"), "failure": f"runtime:{row_failures}"})
            source = str(row.get("source_dataset", ""))
            if source.startswith(FORBIDDEN_PREFIXES):
                failures.append({"id": row.get("id"), "failure": "studyhub_custom_source"})
            if row.get("trajectory_status") != "complete":
                failures.append({"id": row.get("id"), "failure": "action_only"})
            if str(row.get("policy_quality_tier")) == "D":
                failures.append({"id": row.get("id"), "failure": "tier_d"})
            record_id = str(row["id"])
            content_hash = str(row["content_sha256"])
            near_hash = hashlib.sha256(
                f"{near_signature(row)}:{row.get('tool_path_signature', '')}".encode()
            ).hexdigest()
            if record_id in ids:
                failures.append({"id": record_id, "failure": "duplicate_id"})
            if content_hash in exact:
                failures.append({"id": record_id, "failure": "exact_duplicate"})
            seen_near_group = near_groups.get(near_hash)
            if seen_near_group is not None and seen_near_group != str(row["group_id"]):
                failures.append({"id": record_id, "failure": "cross_group_near_lexical_duplicate"})
            ids.add(record_id)
            exact.add(content_hash)
            near_groups.setdefault(near_hash, str(row["group_id"]))
            groups_by_split[str(row["split"])].add(str(row["group_id"]))
            if candidate_prompt_hash(row) in benchmark_hashes:
                benchmark_overlap.append(record_id)
            rows.append(row)

    overlap = {
        "train_validation": len(groups_by_split["train"] & groups_by_split["validation"]),
        "train_protocol_holdout": len(groups_by_split["train"] & groups_by_split["protocol_holdout"]),
        "validation_protocol_holdout": len(groups_by_split["validation"] & groups_by_split["protocol_holdout"]),
    }
    if any(overlap.values()):
        failures.append({"failure": f"split_group_overlap:{overlap}"})
    if benchmark_overlap:
        failures.append({"failure": f"public_benchmark_overlap:{benchmark_overlap[:5]}"})

    dataset = load_from_disk(args.processed / "hf_dataset")
    if {split: len(dataset[split]) for split in dataset} != token_manifest["split_counts"]:
        failures.append({"failure": "processed_split_count_drift"})
    mask_rows_verified = 0
    if not args.skip_mask_recompute:
        tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True, local_files_only=True)
        for split in ("train", "validation", "protocol_holdout"):
            metadata_path = args.processed / "metadata" / f"{split}.jsonl"
            with metadata_path.open(encoding="utf-8") as metadata_stream:
                for tensor, line in zip(dataset[split], metadata_stream, strict=True):
                    row = json.loads(line)
                    expected_ids, expected_mask, rendered = assistant_loss_mask(
                        tokenizer, row["messages"], row["tools"]
                    )
                    if list(tensor["input_ids"]) != expected_ids or list(tensor["loss_mask"]) != expected_mask:
                        failures.append({"id": row["id"], "failure": "loss_mask_or_token_drift"})
                        break
                    if row["tokenization"]["rendered_sha256"] != sha256_text(rendered):
                        failures.append({"id": row["id"], "failure": "rendered_hash_drift"})
                        break
                    mask_rows_verified += 1

    train_rows = [row for row in rows if row["split"] == "train"]
    train_total = sum(int(row["tokenization"]["total_tokens"]) for row in train_rows)
    train_assistant = sum(int(row["tokenization"]["assistant_loss_tokens"]) for row in train_rows)
    family_tokens = Counter()
    behavior_tokens = Counter()
    abstract_tokens = Counter()
    exact_tokens = Counter()
    quality_rows = Counter()
    train_group_rows = Counter()
    train_group_tokens = Counter()
    replay_tokens = 0
    two_wiki_tokens = 0
    for row in train_rows:
        tokens = int(row["tokenization"]["assistant_loss_tokens"])
        train_group_rows[str(row["group_id"])] += 1
        train_group_tokens[str(row["group_id"])] += tokens
        family_tokens[str(row["source_family"])] += tokens
        abstract_tokens[str(row["abstract_tool_path"])] += tokens
        exact_tokens[str(row["tool_path_signature"])] += tokens
        quality_rows[str(row["policy_quality_tier"])] += 1
        for behavior in row["behavior_tags"]:
            behavior_tokens[str(behavior)] += tokens
        if "oracle_replay" in row["behavior_tags"]:
            replay_tokens += tokens
        if row["source_dataset"] == "studyhub_2wiki_replay":
            two_wiki_tokens += tokens

    selection = program["selection"]
    gates: dict[str, bool] = {
        "train_rows": len(train_rows) == int(selection["target_train_rows"]),
        "assistant_token_budget": abs(train_assistant - int(selection["target_assistant_loss_tokens"]))
        <= round(
            int(selection["target_assistant_loss_tokens"]) * float(selection["assistant_loss_token_tolerance_fraction"])
        ),
        "total_token_budget": abs(train_total - int(selection["target_total_tokens"]))
        <= round(int(selection["target_total_tokens"]) * float(selection["total_token_tolerance_fraction"])),
        "action_only_zero": not any(row.get("trajectory_status") != "complete" for row in rows),
        "tier_d_zero": quality_rows.get("D", 0) == 0,
        "benchmark_overlap_zero": not benchmark_overlap,
        "split_overlap_zero": not any(overlap.values()),
        "studyhub_custom_zero": not any(str(row["source_dataset"]).startswith(FORBIDDEN_PREFIXES) for row in rows),
        "largest_abstract_path_below_25pct": max(abstract_tokens.values(), default=0) / train_assistant < 0.25,
        "largest_exact_path_below_25pct": max(exact_tokens.values(), default=0) / train_assistant < 0.25,
        "oracle_replay_at_most_20pct": replay_tokens / train_assistant <= 0.20,
        "two_wiki_at_most_12pct": two_wiki_tokens / train_assistant <= 0.12,
        "conversation_group_cap": max(train_group_rows.values(), default=0)
        <= int(selection["max_rows_per_conversation_group"]),
        "conversation_group_assistant_share_cap": max(train_group_tokens.values(), default=0) / train_assistant
        <= float(selection["largest_conversation_group_assistant_token_share_max"]),
        "semantic_cross_group_duplicates_zero": semantic_evidence["hard_cross_group_pairs"] == 0,
    }
    for family, (minimum, maximum) in selection["source_family_assistant_token_bounds"].items():
        share = family_tokens[family] / train_assistant
        gates[f"family_{family}_share"] = float(minimum) <= share <= float(maximum)
    for behavior, minimum in selection["behavior_minimum_shares"].items():
        gates[f"behavior_{behavior}_minimum"] = behavior_tokens[behavior] / train_assistant >= float(minimum)
    for behavior, maximum in selection["behavior_maximum_shares"].items():
        gates[f"behavior_{behavior}_maximum"] = behavior_tokens[behavior] / train_assistant <= float(maximum)
    if failures or not all(gates.values()):
        raise RuntimeError(
            f"Open-Agentic data gate failed: failures={failures[:10]}, failed_gates="
            f"{[key for key, passed in gates.items() if not passed]}"
        )

    audit = {
        "schema_version": "studyhub.open-agentic-data-audit.v2",
        "status": "PASS",
        "dataset_id": "open-agentic-sft-v2-qwen35-9b",
        "rows": {
            "total": len(rows),
            "train": len(train_rows),
            "validation": sum(row["split"] == "validation" for row in rows),
            "protocol_holdout": sum(row["split"] == "protocol_holdout" for row in rows),
        },
        "tokens": {
            "train_total": train_total,
            "train_assistant_loss": train_assistant,
            "target_assistant_loss": int(selection["target_assistant_loss_tokens"]),
            "assistant_delta": train_assistant - int(selection["target_assistant_loss_tokens"]),
            "target_total": int(selection["target_total_tokens"]),
            "total_delta": train_total - int(selection["target_total_tokens"]),
        },
        "source_family_assistant_shares": {
            key: round(value / train_assistant, 8) for key, value in sorted(family_tokens.items())
        },
        "behavior_assistant_shares": {
            key: round(value / train_assistant, 8) for key, value in sorted(behavior_tokens.items())
        },
        "quality_tier_rows": dict(sorted(quality_rows.items())),
        "abstract_path_assistant_shares": {
            key: round(value / train_assistant, 8) for key, value in sorted(abstract_tokens.items())
        },
        "largest_exact_path_assistant_share": round(max(exact_tokens.values()) / train_assistant, 8),
        "conversation_groups": {
            "unique": len(train_group_rows),
            "rows_per_group": {
                "p50": percentile(list(train_group_rows.values()), 0.50),
                "p90": percentile(list(train_group_rows.values()), 0.90),
                "max": max(train_group_rows.values()),
            },
            "largest_assistant_token_share": round(
                max(train_group_tokens.values(), default=0) / train_assistant,
                8,
            ),
        },
        "source_audit": source_audit(rows),
        "isolation": {
            "public_benchmark_rows_hashed": benchmark_rows,
            "public_benchmark_overlap": 0,
            "sealed_content_read": False,
            "studyhub_custom_rows": 0,
            "split_group_overlap": overlap,
            "exact_duplicates": 0,
            "near_lexical_duplicates": 0,
            "semantic_cross_group_duplicates": 0,
        },
        "loss_mask": {
            "rows_recomputed": mask_rows_verified,
            "system_user_tool_tokens_masked": True,
            "assistant_tool_call_continuation_final_trained": True,
        },
        "gates": gates,
        "lineage": {
            "program_sha256": sha256(args.program),
            "selected_sha256": sha256(args.selected),
            "selected_manifest_sha256": sha256(selected_manifest_path),
            "tokenized_manifest_sha256": sha256(token_manifest_path),
            "benchmark_manifest_sha256": sha256(benchmark_path),
            "semantic_evidence_sha256": sha256(args.semantic_evidence),
        },
        "semantic_dedup": semantic_evidence["contract"],
    }
    write_json(args.evidence, audit)
    write_data_card(args.data_card, audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def write_data_card(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# Open-Agentic SFT v2 Data Card",
        "",
        "## Purpose",
        "",
        "Hermes-centered open-source supervision for the controlled Qwen3.5-9B SFT comparison.",
        "StudyHub deterministic fixtures, teacher reverse replay, and evaluation tasks are excluded.",
        "",
        "## Scale",
        "",
        "| Item | Value |",
        "|---|---:|",
        f"| Train rows | {audit['rows']['train']:,} |",
        f"| Validation rows | {audit['rows']['validation']:,} |",
        f"| Protocol holdout rows | {audit['rows']['protocol_holdout']:,} |",
        f"| Train total tokens | {audit['tokens']['train_total']:,} |",
        f"| Train assistant-loss tokens | {audit['tokens']['train_assistant_loss']:,} |",
        f"| Assistant-token target delta | {audit['tokens']['assistant_delta']:+,} |",
        f"| Total-token target delta | {audit['tokens']['total_delta']:+,} |",
        "",
        "## Source Mix",
        "",
        "| Family | Assistant-loss token share |",
        "|---|---:|",
    ]
    lines.extend(f"| {family} | {share:.2%} |" for family, share in audit["source_family_assistant_shares"].items())
    lines.extend(["", "## Behavior Mix", "", "| Behavior | Assistant-loss token share |", "|---|---:|"])
    lines.extend(f"| {behavior} | {share:.2%} |" for behavior, share in audit["behavior_assistant_shares"].items())
    lines.extend(["", "## Quality Tiers", "", "| Tier | Rows |", "|---|---:|"])
    lines.extend(f"| {tier} | {rows:,} |" for tier, rows in audit["quality_tier_rows"].items())
    lines.extend(
        [
            "",
            "## Tool Paths",
            "",
            "| Abstract path | Assistant-loss token share |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| {tool_path} | {share:.2%} |" for tool_path, share in audit["abstract_path_assistant_shares"].items()
    )
    groups = audit["conversation_groups"]
    lines.extend(
        [
            "",
            "## Group Concentration",
            "",
            f"- Unique train conversation groups: {groups['unique']:,}",
            f"- Rows/group p50, p90, max: {groups['rows_per_group']['p50']}, "
            f"{groups['rows_per_group']['p90']}, {groups['rows_per_group']['max']}",
            f"- Largest group assistant-token share: {groups['largest_assistant_token_share']:.2%}",
            f"- Largest exact tool-path assistant-token share: {audit['largest_exact_path_assistant_share']:.2%}",
            "",
            "## Source Detail",
            "",
            "The table below covers all three splits.",
            "",
            "| Source | Family | Rows | Assistant tokens | Groups | Group p90/max | Calls p50/p90 | "
            "Observation origin | License | Revision |",
            "|---|---|---:|---:|---:|---:|---:|---|---|---|",
        ]
    )
    language = Counter()
    for source, detail in audit["source_audit"].items():
        language.update(detail["language"])
        lines.append(
            f"| {source} | {detail['source_family']} | {detail['rows']:,} | "
            f"{detail['assistant_loss_tokens']:,} | {detail['unique_groups']:,} | "
            f"{detail['rows_per_group']['p90']}/{detail['rows_per_group']['max']} | "
            f"{detail['tool_calls_per_trajectory']['p50']}/"
            f"{detail['tool_calls_per_trajectory']['p90']} | "
            f"{', '.join(detail['observation_origin'])} | {', '.join(detail['licenses'])} | "
            f"{', '.join(detail['revisions'])} |"
        )
    lines.extend(
        [
            "",
            "## Language",
            "",
            "| Language | Rows |",
            "|---|---:|",
            *[f"| {key} | {value:,} |" for key, value in sorted(language.items())],
            "",
            "## Semantic Deduplication",
            "",
            f"- Embedding contract: {audit['semantic_dedup']['embedding']}",
            f"- Neighbor count: {audit['semantic_dedup']['neighbors']}",
            f"- Hard cross-group threshold: {audit['semantic_dedup']['hard_cross_group_threshold']}",
            "- Hard cross-group pairs in the selected dataset: 0",
        ]
    )
    lines.extend(
        [
            "",
            "## Isolation",
            "",
            "- Action-only rows: 0",
            "- StudyHub custom fixture rows: 0",
            "- Public AgentBench prompt overlap: 0",
            "- Sealed content read: false",
            "- Train/validation/protocol source-group overlap: 0",
            "- APIGen-MT: disabled",
            "- xLAM 60k: skipped because access was gated",
            "",
            "## Loss",
            "",
            "Loss is applied only to assistant tool calls, assistant continuations, and final answers. "
            "System, user, and tool-observation tokens are masked.",
            "",
            "## Boundary",
            "",
            "2Wiki and QASPER remain oracle/replay auxiliaries and are capped. "
            "Passing this data audit does not establish downstream Agent capability.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
