#!/usr/bin/env python3
"""Tokenize and select Open-Agentic SFT v2 with a deterministic constrained allocator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for import_root in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.data.select_runtime_sft_v3 import sha256  # noqa: E402
from scripts.data.tokenize_runtime_sft_v3 import assistant_loss_mask  # noqa: E402
from studyhub_agent.trajectory.runtime_sft import stable_hash, validate_runtime_trajectory  # noqa: E402


@dataclass(frozen=True)
class InventoryRow:
    record_id: str
    position: int
    split: str
    source: str
    source_family: str
    group_id: str
    total_tokens: int
    assistant_tokens: int
    behaviors: tuple[str, ...]
    abstract_path: str
    exact_path: str
    quality_tier: str
    stable_order: str


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


def build_inventory(
    candidate: Path,
    tokenizer: Any,
    *,
    max_length: int,
) -> tuple[list[InventoryRow], Counter[str]]:
    inventory: list[InventoryRow] = []
    excluded: Counter[str] = Counter()
    with candidate.open(encoding="utf-8") as stream:
        for position, line in enumerate(stream):
            row = json.loads(line)
            failures = validate_runtime_trajectory(row)
            if failures:
                raise RuntimeError(f"candidate runtime contract failure: {row.get('id')}: {failures}")
            input_ids, loss_mask, _rendered = assistant_loss_mask(tokenizer, row["messages"], row["tools"])
            if len(input_ids) > max_length:
                excluded[f"too_long:{row.get('source_family', 'unknown')}"] += 1
                continue
            assistant_tokens = int(sum(loss_mask))
            if assistant_tokens <= 0:
                raise RuntimeError(f"candidate has no assistant loss tokens: {row.get('id')}")
            inventory.append(
                InventoryRow(
                    record_id=str(row["id"]),
                    position=position,
                    split=str(row["split"]),
                    source=str(row["source_dataset"]),
                    source_family=str(row["source_family"]),
                    group_id=str(row["group_id"]),
                    total_tokens=len(input_ids),
                    assistant_tokens=assistant_tokens,
                    behaviors=tuple(sorted(map(str, row.get("behavior_tags", [])))),
                    abstract_path=str(row.get("abstract_tool_path", "unknown")),
                    exact_path=str(row.get("tool_path_signature", "unknown")),
                    quality_tier=str(row.get("policy_quality_tier", "unknown")),
                    stable_order=stable_hash(str(row["id"]), salt="open-agentic-sft-v2-allocator-20260827"),
                )
            )
    return inventory, excluded


def write_inventory_cache(
    path: Path,
    rows: list[InventoryRow],
    excluded: Counter[str],
    *,
    lineage: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(asdict(row), ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)
    write_json(
        path.with_suffix(".manifest.json"),
        {
            "schema_version": "studyhub.open-agentic-token-inventory.v1",
            "status": "TOKEN_INVENTORY_COMPLETE",
            "rows": len(rows),
            "excluded": dict(sorted(excluded.items())),
            "lineage": lineage,
            "output_sha256": sha256(path),
        },
    )


def load_inventory_cache(
    path: Path,
    *,
    expected_lineage: dict[str, Any],
) -> tuple[list[InventoryRow], Counter[str]] | None:
    manifest_path = path.with_suffix(".manifest.json")
    if not path.is_file() or not manifest_path.is_file():
        return None
    manifest = load_json(manifest_path)
    if (
        manifest.get("status") != "TOKEN_INVENTORY_COMPLETE"
        or manifest.get("lineage") != expected_lineage
        or manifest.get("output_sha256") != sha256(path)
    ):
        return None
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            payload = json.loads(line)
            payload["behaviors"] = tuple(payload["behaviors"])
            rows.append(InventoryRow(**payload))
    if len(rows) != int(manifest["rows"]):
        raise RuntimeError("token inventory row count drift")
    excluded = Counter({str(key): int(value) for key, value in manifest["excluded"].items()})
    return rows, excluded


def solve_train(rows: list[InventoryRow], program: dict[str, Any]) -> tuple[list[InventoryRow], dict[str, Any]]:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    selection = program["selection"]
    target_rows = int(selection["target_train_rows"])
    target_assistant = int(selection["target_assistant_loss_tokens"])
    target_total = int(selection["target_total_tokens"])
    assistant_tolerance = float(selection["assistant_loss_token_tolerance_fraction"])
    total_tolerance = float(selection["total_token_tolerance_fraction"])
    family_bounds = selection["source_family_assistant_token_bounds"]
    family_targets = selection["source_family_target_shares"]
    behavior_minimums = selection["behavior_minimum_shares"]
    behavior_maximums = selection["behavior_maximum_shares"]
    path_maximum = float(selection["largest_abstract_tool_path_share_max"])
    two_wiki_maximum = float(selection["two_wiki_assistant_token_share_max"])
    max_rows_per_group = int(selection["max_rows_per_conversation_group"])

    if target_rows > len(rows):
        raise RuntimeError(f"insufficient train candidates: {len(rows)} < {target_rows}")
    families = sorted(family_targets)
    if set(family_bounds) != set(families) or abs(sum(map(float, family_targets.values())) - 1.0) > 1e-9:
        raise RuntimeError("invalid source-family allocation contract")

    base_variables = len(rows)
    variable_count = base_variables + 2 * len(families)
    objective = np.zeros(variable_count, dtype=np.float64)
    group_counts = Counter(row.group_id for row in rows)
    exact_path_counts = Counter(row.exact_path for row in rows)
    quality_penalty = {"A": 0.0, "B": 2.0e-7, "C": 1.0e-6, "D": 1.0}
    for index, row in enumerate(rows):
        concentration = max(group_counts[row.group_id] - 1, 0) + max(exact_path_counts[row.exact_path] - 1, 0)
        tie = int(row.stable_order[:8], 16) / 0xFFFFFFFF
        objective[index] = quality_penalty.get(row.quality_tier, 5.0e-7) + concentration * 1.0e-9 + tie * 1.0e-12
    for family_index, family in enumerate(families):
        target = max(float(family_targets[family]) * target_assistant, 1.0)
        objective[base_variables + 2 * family_index] = 1.0 / target
        objective[base_variables + 2 * family_index + 1] = 1.0 / target

    row_indices: list[int] = []
    column_indices: list[int] = []
    values: list[float] = []
    lower: list[float] = []
    upper: list[float] = []

    def add_constraint(coefficients: dict[int, float], minimum: float, maximum: float) -> None:
        constraint_index = len(lower)
        for column, value in coefficients.items():
            if value:
                row_indices.append(constraint_index)
                column_indices.append(column)
                values.append(float(value))
        lower.append(float(minimum))
        upper.append(float(maximum))

    add_constraint({index: 1.0 for index in range(base_variables)}, target_rows, target_rows)
    assistant_coefficients = {index: row.assistant_tokens for index, row in enumerate(rows)}
    total_coefficients = {index: row.total_tokens for index, row in enumerate(rows)}
    add_constraint(
        assistant_coefficients,
        target_assistant * (1.0 - assistant_tolerance),
        target_assistant * (1.0 + assistant_tolerance),
    )
    add_constraint(
        total_coefficients,
        target_total * (1.0 - total_tolerance),
        target_total * (1.0 + total_tolerance),
    )

    for family in families:
        minimum, maximum = map(float, family_bounds[family])
        add_constraint(
            {
                index: row.assistant_tokens * ((1.0 if row.source_family == family else 0.0) - minimum)
                for index, row in enumerate(rows)
            },
            0.0,
            np.inf,
        )
        add_constraint(
            {
                index: row.assistant_tokens * ((1.0 if row.source_family == family else 0.0) - maximum)
                for index, row in enumerate(rows)
            },
            -np.inf,
            0.0,
        )

    for behavior, minimum in behavior_minimums.items():
        minimum = float(minimum)
        add_constraint(
            {
                index: row.assistant_tokens * ((1.0 if behavior in row.behaviors else 0.0) - minimum)
                for index, row in enumerate(rows)
            },
            0.0,
            np.inf,
        )
    for behavior, maximum in behavior_maximums.items():
        maximum = float(maximum)
        add_constraint(
            {
                index: row.assistant_tokens * ((1.0 if behavior in row.behaviors else 0.0) - maximum)
                for index, row in enumerate(rows)
            },
            -np.inf,
            0.0,
        )

    for path in sorted({row.abstract_path for row in rows}):
        add_constraint(
            {
                index: row.assistant_tokens * ((1.0 if row.abstract_path == path else 0.0) - path_maximum)
                for index, row in enumerate(rows)
            },
            -np.inf,
            0.0,
        )
    add_constraint(
        {
            index: row.assistant_tokens
            * ((1.0 if row.source == "studyhub_2wiki_replay" else 0.0) - two_wiki_maximum)
            for index, row in enumerate(rows)
        },
        -np.inf,
        0.0,
    )

    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[row.group_id].append(index)
    for indices in grouped.values():
        if len(indices) > max_rows_per_group:
            add_constraint({index: 1.0 for index in indices}, 0.0, float(max_rows_per_group))

    for family_index, family in enumerate(families):
        positive = base_variables + 2 * family_index
        negative = positive + 1
        target_share = float(family_targets[family])
        coefficients = {
            index: row.assistant_tokens * ((1.0 if row.source_family == family else 0.0) - target_share)
            for index, row in enumerate(rows)
        }
        coefficients[positive] = -1.0
        coefficients[negative] = 1.0
        add_constraint(coefficients, 0.0, 0.0)

    matrix = coo_matrix(
        (values, (row_indices, column_indices)),
        shape=(len(lower), variable_count),
        dtype=np.float64,
    ).tocsr()
    variable_lower = np.zeros(variable_count, dtype=np.float64)
    variable_upper = np.concatenate(
        [np.ones(base_variables, dtype=np.float64), np.full(2 * len(families), np.inf, dtype=np.float64)]
    )
    integrality = np.concatenate(
        [np.ones(base_variables, dtype=np.int8), np.zeros(2 * len(families), dtype=np.int8)]
    )
    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(variable_lower, variable_upper),
        constraints=LinearConstraint(matrix, np.asarray(lower), np.asarray(upper)),
        options={"time_limit": 600.0, "mip_rel_gap": 0.001, "presolve": True},
    )
    if result.x is None or result.status not in {0, 1}:
        raise RuntimeError(f"constrained allocator failed: status={result.status}, message={result.message}")
    selected = [row for index, row in enumerate(rows) if result.x[index] > 0.5]
    if len(selected) != target_rows:
        raise RuntimeError(f"allocator returned {len(selected)} rows instead of {target_rows}")
    selected.sort(key=lambda row: row.stable_order)
    diagnostics = {
        "solver": "scipy.optimize.milp/HiGHS",
        "status": int(result.status),
        "message": str(result.message),
        "objective": float(result.fun),
        "mip_gap": None if getattr(result, "mip_gap", None) is None else float(result.mip_gap),
        "node_count": None if getattr(result, "mip_node_count", None) is None else int(result.mip_node_count),
        "constraints": len(lower),
        "binary_variables": base_variables,
    }
    return selected, diagnostics


def select_eval_split(
    rows: list[InventoryRow],
    target: int,
    train_family_counts: Counter[str],
) -> list[InventoryRow]:
    if target > len(rows):
        raise RuntimeError(f"insufficient evaluation candidates: {len(rows)} < {target}")
    total_train = sum(train_family_counts.values())
    families = sorted(train_family_counts)
    quotas = {family: math.floor(target * train_family_counts[family] / total_train) for family in families}
    remainder = target - sum(quotas.values())
    fractional = sorted(
        families,
        key=lambda family: (
            -(target * train_family_counts[family] / total_train - quotas[family]),
            family,
        ),
    )
    for family in fractional[:remainder]:
        quotas[family] += 1
    grouped: dict[str, list[InventoryRow]] = defaultdict(list)
    for row in rows:
        grouped[row.source_family].append(row)
    selected: list[InventoryRow] = []
    for family in families:
        candidates = sorted(grouped[family], key=lambda row: row.stable_order)
        selected.extend(candidates[: min(quotas[family], len(candidates))])
    if len(selected) < target:
        used = {row.record_id for row in selected}
        residual = sorted((row for row in rows if row.record_id not in used), key=lambda row: row.stable_order)
        selected.extend(residual[: target - len(selected)])
    return sorted(selected, key=lambda row: row.stable_order)


def summarize(rows: list[InventoryRow]) -> dict[str, Any]:
    assistant_total = sum(row.assistant_tokens for row in rows)
    total_tokens = sum(row.total_tokens for row in rows)
    family_tokens = Counter()
    family_rows = Counter()
    behavior_tokens = Counter()
    abstract_tokens = Counter()
    exact_tokens = Counter()
    source_tokens = Counter()
    lengths = []
    for row in rows:
        family_tokens[row.source_family] += row.assistant_tokens
        family_rows[row.source_family] += 1
        source_tokens[row.source] += row.assistant_tokens
        abstract_tokens[row.abstract_path] += row.assistant_tokens
        exact_tokens[row.exact_path] += row.assistant_tokens
        lengths.append(row.total_tokens)
        for behavior in row.behaviors:
            behavior_tokens[behavior] += row.assistant_tokens
    return {
        "rows": len(rows),
        "total_tokens": total_tokens,
        "assistant_loss_tokens": assistant_total,
        "assistant_fraction": round(assistant_total / total_tokens, 8),
        "source_family_rows": dict(sorted(family_rows.items())),
        "source_family_assistant_tokens": dict(sorted(family_tokens.items())),
        "source_family_assistant_shares": {
            key: round(value / assistant_total, 8) for key, value in sorted(family_tokens.items())
        },
        "source_assistant_tokens": dict(sorted(source_tokens.items())),
        "behavior_assistant_tokens": dict(sorted(behavior_tokens.items())),
        "behavior_assistant_shares": {
            key: round(value / assistant_total, 8) for key, value in sorted(behavior_tokens.items())
        },
        "abstract_path_assistant_tokens": dict(sorted(abstract_tokens.items())),
        "abstract_path_assistant_shares": {
            key: round(value / assistant_total, 8) for key, value in sorted(abstract_tokens.items())
        },
        "largest_exact_path_assistant_share": round(max(exact_tokens.values(), default=0) / assistant_total, 8),
        "token_lengths": {
            "min": min(lengths),
            "p50": percentile(lengths, 0.50),
            "p90": percentile(lengths, 0.90),
            "p95": percentile(lengths, 0.95),
            "p99": percentile(lengths, 0.99),
            "max": max(lengths),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--program",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-agentic-sft-v2.json",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/candidates.jsonl",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_ROOT.parent / "models/P1/Qwen3.5-9B",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.jsonl",
    )
    parser.add_argument(
        "--processed-output",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/open_agentic_sft_v2_qwen35_9b",
    )
    parser.add_argument(
        "--inventory-cache",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/token-inventory.jsonl",
    )
    parser.add_argument("--max-length", type=int, default=8192)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from transformers import AutoTokenizer

    from datasets import Dataset, DatasetDict

    program = load_json(args.program)
    candidate_manifest_path = args.candidate.with_suffix(".manifest.json")
    candidate_manifest = load_json(candidate_manifest_path)
    if candidate_manifest.get("status") != "CANDIDATE_BUILD_PASS":
        raise RuntimeError("candidate manifest is not accepted")
    if candidate_manifest["lineage"]["output_sha256"] != sha256(args.candidate):
        raise RuntimeError("candidate lineage drift")
    model_manifest_path = args.model / "studyhub_download_manifest.json"
    if sha256(model_manifest_path) != program["model"]["manifest_sha256"]:
        raise RuntimeError("model manifest drift")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True, local_files_only=True)
    inventory_lineage = {
        "candidate_sha256": sha256(args.candidate),
        "model_manifest_sha256": sha256(model_manifest_path),
        "tokenizer_revision": program["model"]["revision"],
        "max_length": args.max_length,
    }
    cached = load_inventory_cache(args.inventory_cache, expected_lineage=inventory_lineage)
    if cached is None:
        inventory, excluded = build_inventory(args.candidate, tokenizer, max_length=args.max_length)
        write_inventory_cache(
            args.inventory_cache,
            inventory,
            excluded,
            lineage=inventory_lineage,
        )
    else:
        inventory, excluded = cached
    by_split: dict[str, list[InventoryRow]] = defaultdict(list)
    for row in inventory:
        by_split[row.split].append(row)
    selected_train, solver = solve_train(by_split["train"], program)
    family_counts = Counter(row.source_family for row in selected_train)
    eval_target = round(int(program["selection"]["target_train_rows"]) / 18)
    selected_validation = select_eval_split(by_split["validation"], eval_target, family_counts)
    selected_protocol = select_eval_split(by_split["protocol_holdout"], eval_target, family_counts)
    selected_by_split = {
        "train": selected_train,
        "validation": selected_validation,
        "protocol_holdout": selected_protocol,
    }
    selected_ids = {
        split: {row.record_id for row in rows} for split, rows in selected_by_split.items()
    }
    selected_inventory = {row.record_id: row for rows in selected_by_split.values() for row in rows}

    if args.output.exists() or args.processed_output.exists():
        if not args.overwrite:
            raise FileExistsError("selected output exists; pass --overwrite")
        args.output.unlink(missing_ok=True)
        shutil.rmtree(args.processed_output, ignore_errors=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = args.processed_output.with_name(args.processed_output.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    metadata_root = staging / "metadata"
    metadata_root.mkdir()

    tensors: dict[str, dict[str, list[list[int]]]] = {
        split: {"input_ids": [], "loss_mask": []} for split in selected_by_split
    }
    metadata_streams = {
        split: (metadata_root / f"{split}.jsonl").open("w", encoding="utf-8")
        for split in selected_by_split
    }
    selected_temporary = args.output.with_suffix(args.output.suffix + ".partial")
    with selected_temporary.open("w", encoding="utf-8") as selected_output:
        try:
            with args.candidate.open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    split = str(row["split"])
                    record_id = str(row["id"])
                    if record_id not in selected_ids[split]:
                        continue
                    input_ids, loss_mask, rendered = assistant_loss_mask(tokenizer, row["messages"], row["tools"])
                    inventory_row = selected_inventory[record_id]
                    if len(input_ids) != inventory_row.total_tokens or sum(loss_mask) != inventory_row.assistant_tokens:
                        raise RuntimeError(f"tokenization drift on second pass: {record_id}")
                    row["tokenization"] = {
                        "total_tokens": len(input_ids),
                        "assistant_loss_tokens": int(sum(loss_mask)),
                        "rendered_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                    }
                    selected_output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    metadata_streams[split].write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    tensors[split]["input_ids"].append(input_ids)
                    tensors[split]["loss_mask"].append(loss_mask)
        finally:
            for metadata_stream in metadata_streams.values():
                metadata_stream.close()
    os.replace(selected_temporary, args.output)
    DatasetDict(
        {split: Dataset.from_dict(values) for split, values in tensors.items()}
    ).save_to_disk(staging / "hf_dataset")

    summaries = {split: summarize(rows) for split, rows in selected_by_split.items()}
    manifest = {
        "schema_version": "studyhub.open-agentic-tokenized-manifest.v2",
        "status": "TOKENIZED_PENDING_FINAL_DATA_GATE",
        "model_tokenizer": str(args.model.resolve()),
        "tokenizer_revision": program["model"]["revision"],
        "max_length": args.max_length,
        "candidate_exclusions": dict(sorted(excluded.items())),
        "split_counts": {split: len(rows) for split, rows in selected_by_split.items()},
        "summaries": summaries,
        "solver": solver,
        "lineage": {
            "program_sha256": sha256(args.program),
            "candidate_sha256": sha256(args.candidate),
            "candidate_manifest_sha256": sha256(candidate_manifest_path),
            "selected_sha256": sha256(args.output),
        },
    }
    write_json(staging / "manifest.json", manifest)
    os.replace(staging, args.processed_output)
    selected_manifest = {
        "schema_version": "studyhub.open-agentic-selected-manifest.v2",
        "status": "SELECTED_AND_TOKENIZED_DATA_GATE_PENDING",
        "split_counts": manifest["split_counts"],
        "train_summary": summaries["train"],
        "solver": solver,
        "benchmark_lock": program["benchmark_lock"],
        "output_sha256": sha256(args.output),
        "tokenized_manifest_sha256": sha256(args.processed_output / "manifest.json"),
    }
    write_json(args.output.with_suffix(".manifest.json"), selected_manifest)
    print(json.dumps(selected_manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
