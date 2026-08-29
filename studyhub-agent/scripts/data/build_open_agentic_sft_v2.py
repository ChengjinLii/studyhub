#!/usr/bin/env python3
"""Build the normalized, deduplicated Open-Agentic SFT v2 candidate pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for import_root in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.data.select_runtime_sft_v3 import (  # noqa: E402
    candidate_prompt_hash,
    near_signature,
    normalized_text,
    public_benchmark_prompt_hashes,
    semantic_template,
    sha256,
)
from studyhub_agent.trajectory.open_agentic import (  # noqa: E402
    add_policy_metadata,
    iter_hermes_records,
    iter_json_array,
    parse_agent_flan_negative,
    parse_agent_flan_toolbench_react,
    parse_toolbench_record,
)
from studyhub_agent.trajectory.runtime_sft import (  # noqa: E402
    stable_hash,
    trajectory_fingerprint,
    validate_runtime_trajectory,
)

AUXILIARY_SOURCES = {
    "studyhub_2wiki_replay": "rag_replay",
    "studyhub_qasper_replay": "rag_replay",
    "coig_exam": "coig",
    "toolace": "toolace",
}
DISALLOWED_SOURCE_PREFIXES = (
    "studyhub_metadata",
    "studyhub_memory",
    "studyhub_acl",
    "studyhub_web",
    "studyhub_state",
    "studyhub_teacher",
)
SEMANTIC_TEMPLATE_CAPS = {"hermes": 64, "other_families": 8}


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


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"expected object at {path}:{line_number}")
            yield value


def first_user(record: dict[str, Any]) -> str:
    return next(
        (
            str(message.get("content", ""))
            for message in record.get("messages", [])
            if message.get("role") == "user"
        ),
        "",
    )


def split_for_group(group_id: str) -> str:
    bucket = int(stable_hash(group_id, salt="open-agentic-sft-v2-split-20260827")[:8], 16) % 10_000
    if bucket < 9_000:
        return "train"
    if bucket < 9_500:
        return "validation"
    return "protocol_holdout"


def verify_registered_files(registry: dict[str, Any], roots: dict[str, Path]) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    for source, root in roots.items():
        entry = registry["sources"][source]
        if not str(entry.get("status", "")).startswith("ENABLED"):
            raise RuntimeError(f"source is not enabled: {source}")
        file_inventory = {}
        for relative, expected in entry["files"].items():
            path = root / relative
            if not path.is_file():
                raise FileNotFoundError(path)
            actual = sha256(path)
            if actual != expected:
                raise RuntimeError(f"raw source hash drift: {path}: {actual} != {expected}")
            file_inventory[relative] = {"sha256": actual, "bytes": path.stat().st_size}
        inventory[source] = file_inventory
    return inventory


def normalize_auxiliary(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    source = str(row.get("source_dataset", ""))
    if source not in AUXILIARY_SOURCES:
        if source.startswith(DISALLOWED_SOURCE_PREFIXES):
            return None, "auxiliary:studyhub_custom_disallowed"
        return None, "auxiliary:not_selected"
    if row.get("trajectory_status") != "complete":
        return None, f"{source}:action_only_or_incomplete"
    record = deepcopy(row)
    record["source_family"] = AUXILIARY_SOURCES[source]
    if source in {"studyhub_2wiki_replay", "studyhub_qasper_replay"}:
        record["behavior_tags"] = sorted(set(record.get("behavior_tags", [])) | {"oracle_replay"})
    add_policy_metadata(record)
    if source in {"studyhub_2wiki_replay", "studyhub_qasper_replay"}:
        record["behavior_tags"] = sorted(set(record["behavior_tags"]) | {"oracle_replay"})
    if source == "toolace":
        record["policy_quality_tier"] = "B"
    record["provenance"] = dict(record.get("provenance", {}))
    record["provenance"]["open_agentic_transform"] = "reuse-audited-runtime-row-v1"
    record["content_sha256"] = trajectory_fingerprint(record)
    failures = validate_runtime_trajectory(record)
    if failures:
        return None, f"{source}:runtime_contract:{','.join(failures)}"
    return record, "accepted"


class CandidateWriter:
    def __init__(self, output: Path, benchmark_hashes: set[str]) -> None:
        self.output = output
        self.benchmark_hashes = benchmark_hashes
        self.stream = output.open("w", encoding="utf-8")
        self.ids: set[str] = set()
        self.exact: set[str] = set()
        self.user_families: dict[str, set[str]] = {}
        self.near_groups: dict[str, str] = {}
        self.template_counts: Counter[tuple[str, str]] = Counter()
        self.source_ids: set[tuple[str, str]] = set()
        self.accepted = Counter()
        self.behaviors = Counter()
        self.paths = Counter()
        self.splits = Counter()
        self.rejected = Counter()
        self.groups_by_split: dict[str, set[str]] = {
            "train": set(),
            "validation": set(),
            "protocol_holdout": set(),
        }

    def close(self) -> None:
        self.stream.close()

    def reject(self, reason: str) -> None:
        self.rejected[reason] += 1

    def add(self, record: dict[str, Any] | None, reason: str) -> bool:
        if record is None:
            self.reject(reason)
            return False
        source = str(record.get("source_dataset", ""))
        source_family = str(record.get("source_family", ""))
        if not source_family:
            self.reject(f"{source}:missing_source_family")
            return False
        if record.get("trajectory_status") != "complete":
            self.reject(f"{source}:action_only_or_incomplete")
            return False
        failures = validate_runtime_trajectory(record)
        if failures:
            self.reject(f"{source}:runtime_contract:{','.join(failures)}")
            return False
        record_id = str(record.get("id", ""))
        source_key = (source, str(record.get("source_id", "")))
        content_hash = str(record.get("content_sha256", ""))
        user_hash = hashlib.sha256(normalized_text(first_user(record)).encode()).hexdigest()
        near_hash = hashlib.sha256(
            f"{near_signature(record)}:{record.get('tool_path_signature', '')}".encode()
        ).hexdigest()
        template_key = (source_family, semantic_template(record))
        if not record_id or record_id in self.ids:
            self.reject(f"{source}:duplicate_record_id")
            return False
        if not content_hash or content_hash in self.exact:
            self.reject(f"{source}:exact_duplicate")
            return False
        if source_key in self.source_ids:
            self.reject(f"{source}:duplicate_source_id")
            return False
        seen_families = self.user_families.get(user_hash, set())
        if seen_families and source_family not in seen_families:
            self.reject(f"{source}:cross_source_conversation_duplicate")
            return False
        seen_near_group = self.near_groups.get(near_hash)
        if seen_near_group is not None and seen_near_group != str(record["group_id"]):
            self.reject(f"{source}:cross_group_near_lexical_duplicate")
            return False
        template_cap = (
            SEMANTIC_TEMPLATE_CAPS["hermes"]
            if source_family == "hermes"
            else SEMANTIC_TEMPLATE_CAPS["other_families"]
        )
        if self.template_counts[template_key] >= template_cap:
            self.reject(f"{source}:semantic_template_path_cap")
            return False
        if candidate_prompt_hash(record) in self.benchmark_hashes:
            self.reject(f"{source}:public_benchmark_overlap")
            return False

        split = split_for_group(str(record["group_id"]))
        record["split"] = split
        record["content_sha256"] = trajectory_fingerprint(record)
        self.stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self.ids.add(record_id)
        self.exact.add(content_hash)
        self.source_ids.add(source_key)
        self.user_families.setdefault(user_hash, set()).add(source_family)
        self.near_groups.setdefault(near_hash, str(record["group_id"]))
        self.template_counts[template_key] += 1
        self.accepted[source_family] += 1
        self.behaviors.update(map(str, record.get("behavior_tags", [])))
        self.paths[str(record.get("abstract_tool_path", "unknown"))] += 1
        self.splits[split] += 1
        self.groups_by_split[split].add(str(record["group_id"]))
        return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=PROJECT_ROOT / "data_registry/open_agentic_sft_v2_sources.json",
    )
    parser.add_argument(
        "--hermes-root",
        type=Path,
        default=PROJECT_ROOT / "datasets/raw/open_source/hermes_function_calling",
    )
    parser.add_argument(
        "--toolbench-root",
        type=Path,
        default=PROJECT_ROOT / "datasets/raw/open_source/toolbench",
    )
    parser.add_argument(
        "--agent-flan-root",
        type=Path,
        default=PROJECT_ROOT / "datasets/raw/open_source/agent_flan",
    )
    parser.add_argument(
        "--auxiliary",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3/selected.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/candidates.jsonl",
    )
    parser.add_argument("--max-toolbench-rows", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_json(args.registry)
    raw_inventory = verify_registered_files(
        registry,
        {
            "hermes_function_calling_v1": args.hermes_root,
            "toolbench": args.toolbench_root,
            "agent_flan": args.agent_flan_root,
        },
    )
    benchmark_manifest_path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark_manifest = load_json(benchmark_manifest_path)
    benchmark_hashes, benchmark_rows = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark_manifest)

    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"output exists; pass --overwrite: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    writer = CandidateWriter(temporary, benchmark_hashes)
    source_inventory = Counter()
    try:
        hermes = registry["sources"]["hermes_function_calling_v1"]
        for record, reason in iter_hermes_records(
            args.hermes_root,
            revision=str(hermes["revision"]),
            license_name=str(hermes["license"]),
            source_url=str(hermes["url"]),
        ):
            source_inventory["hermes_rows_seen"] += 1
            writer.add(record, reason)

        agent_flan = registry["sources"]["agent_flan"]
        for row in iter_jsonl(args.agent_flan_root / "data/toolbench_react_10p.jsonl"):
            source_inventory["agent_flan_react_rows_seen"] += 1
            writer.add(
                *parse_agent_flan_toolbench_react(
                    row,
                    revision=str(agent_flan["revision"]),
                    license_name=str(agent_flan["license"]),
                    source_url=str(agent_flan["url"]),
                )
            )
        for row in iter_jsonl(args.agent_flan_root / "data/toolbench_negative.jsonl"):
            source_inventory["agent_flan_negative_rows_seen"] += 1
            writer.add(
                *parse_agent_flan_negative(
                    row,
                    revision=str(agent_flan["revision"]),
                    license_name=str(agent_flan["license"]),
                    source_url=str(agent_flan["url"]),
                )
            )

        toolbench = registry["sources"]["toolbench"]
        toolbench_train = args.toolbench_root / "extracted/toolllama_G123_dfs_train.json"
        for index, row in enumerate(iter_json_array(toolbench_train), 1):
            source_inventory["toolbench_rows_seen"] += 1
            writer.add(
                *parse_toolbench_record(
                    row,
                    revision=str(toolbench["revision"]),
                    license_name=str(toolbench["license"]),
                    source_url=str(toolbench["url"]),
                    archive_sha256=str(toolbench["files"]["data.zip"]),
                )
            )
            if args.max_toolbench_rows and index >= args.max_toolbench_rows:
                break

        for row in iter_jsonl(args.auxiliary):
            source_inventory["auxiliary_rows_seen"] += 1
            record, reason = normalize_auxiliary(row)
            if record is not None or reason != "auxiliary:not_selected":
                writer.add(record, reason)
    finally:
        writer.close()

    overlap = {
        "train_validation": len(writer.groups_by_split["train"] & writer.groups_by_split["validation"]),
        "train_protocol_holdout": len(
            writer.groups_by_split["train"] & writer.groups_by_split["protocol_holdout"]
        ),
        "validation_protocol_holdout": len(
            writer.groups_by_split["validation"] & writer.groups_by_split["protocol_holdout"]
        ),
    }
    if any(overlap.values()):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"candidate split group overlap: {overlap}")
    os.replace(temporary, args.output)
    manifest = {
        "schema_version": "studyhub.open-agentic-candidate-manifest.v2",
        "status": "CANDIDATE_BUILD_PASS",
        "seed": 20260827,
        "rows": sum(writer.accepted.values()),
        "source_family_rows": dict(sorted(writer.accepted.items())),
        "behavior_rows": dict(sorted(writer.behaviors.items())),
        "abstract_tool_paths": dict(sorted(writer.paths.items())),
        "split_rows": dict(sorted(writer.splits.items())),
        "rejections": dict(sorted(writer.rejected.items())),
        "source_inventory": dict(sorted(source_inventory.items())),
        "raw_inventory": raw_inventory,
        "dedup": {
            "exact_normalized": True,
            "conversation_root": True,
            "near_lexical_user_final_tool_path": True,
            "semantic_template_path_cap": SEMANTIC_TEMPLATE_CAPS,
            "semantic_embedding": "NOT_RUN_CPU_BUILD_PHASE",
        },
        "isolation": {
            "public_benchmark_rows_hashed": benchmark_rows,
            "public_benchmark_overlap": 0,
            "sealed_content_read": False,
            "studyhub_custom_rows": 0,
            "action_only_rows": 0,
            "split_group_overlap": overlap,
        },
        "lineage": {
            "registry_sha256": sha256(args.registry),
            "benchmark_manifest_sha256": sha256(benchmark_manifest_path),
            "auxiliary_sha256": sha256(args.auxiliary),
            "output_sha256": sha256(args.output),
        },
    }
    write_json(args.output.with_suffix(".manifest.json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
