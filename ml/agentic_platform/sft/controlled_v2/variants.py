"""Build equal-budget data and representation variants for SFT attribution."""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..spec import canonical_json, load_jsonl, sha256_file
from .contract import ControlledPaths, ExperimentSpec
from .prepare import _page_evidence_rows, _pressure_case

ROUTER_FIXED_OPTIMIZER_STEPS = 185
TUTOR_FIXED_OPTIMIZER_STEPS = 120
ROUTER_DATA_FRACTIONS = (0.25, 0.50, 0.75, 1.0)
ROUTER_REPLAY_RATIOS = (0.0, 0.10, 0.25, 0.40)
ROUTER_STATE_VARIANTS = ("raw", "runtime_state", "mixed")
TUTOR_NEGATIVE_RATIOS = (0.15, 0.30, 0.45)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _replica(row: Mapping[str, Any], replica: int) -> dict[str, Any]:
    result = copy.deepcopy(row)
    if replica == 0:
        return result
    result["example_id"] = f"{row['example_id']}_mix{replica:02d}"
    for message in result["messages"]:
        if message["role"] != "user":
            continue
        payload = json.loads(message["content"])
        payload["controlled_mixture_replica"] = replica
        message["content"] = canonical_json(payload)
    return result


def _balanced_sample(
    rows: Sequence[Mapping[str, Any]],
    count: int,
    *,
    seed: int,
    group_fields: Sequence[str] = ("task_family",),
) -> list[dict[str, Any]]:
    if count < 0 or not rows:
        raise ValueError(
            "balanced sample requires a non-empty pool and nonnegative count"
        )
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in group_fields)
        groups[key].append(row)
    rng = random.Random(seed)
    for values in groups.values():
        values.sort(key=lambda item: str(item["example_id"]))
        rng.shuffle(values)
    keys = sorted(groups)
    positions = Counter()
    selected: list[dict[str, Any]] = []
    cursor = 0
    while len(selected) < count:
        key = keys[cursor % len(keys)]
        values = groups[key]
        position = positions[key]
        source = values[position % len(values)]
        selected.append(_replica(source, position // len(values)))
        positions[key] += 1
        cursor += 1
    return selected


def _stratified_fraction(
    rows: Sequence[Mapping[str, Any]], fraction: float, *, seed: int
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        runtime_path = str(
            (row.get("remediation_contract") or {}).get("runtime_path") or "unknown"
        )
        grouped[(str(row["task_family"]), runtime_path)].append(row)
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    target_total = round(len(rows) * fraction)
    allocations = {
        key: math.floor(len(values) * fraction) for key, values in grouped.items()
    }
    remainder_order = sorted(
        grouped,
        key=lambda key: (
            -(len(grouped[key]) * fraction - allocations[key]),
            key,
        ),
    )
    for key in remainder_order[: target_total - sum(allocations.values())]:
        allocations[key] += 1
    for key, values in sorted(grouped.items()):
        values = sorted(values, key=lambda item: str(item["example_id"]))
        rng.shuffle(values)
        keep = allocations[key]
        selected.extend(copy.deepcopy(values[:keep]))
    if len(selected) != target_total:
        raise AssertionError(
            "stratified fraction did not preserve the exact target size"
        )
    return sorted(selected, key=lambda item: str(item["example_id"]))


def _export_sharegpt(
    *,
    rows: Sequence[Mapping[str, Any]],
    variant_dir: Path,
    task: str,
    variant: str,
    source_sha256: str,
    design: Mapping[str, Any],
) -> dict[str, Any]:
    dataset_prefix = (
        "studyhub_router_2b" if task == "router" else "studyhub_grounded_tutor_9b"
    )
    file_prefix = "router_tool_2b" if task == "router" else "grounded_tutor_9b"
    dataset_dir = variant_dir / "llamafactory"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_split[str(row["split"])].append(
            {
                "messages": [
                    {"role": item["role"], "content": item["content"]}
                    for item in row["messages"]
                ],
                "example_id": row["example_id"],
                "task_family": row["task_family"],
            }
        )
    dataset_info: dict[str, Any] = {}
    files: dict[str, Any] = {}
    for split in ("train", "validation"):
        split_rows = by_split[split]
        filename = f"{file_prefix}_{split}.jsonl"
        path = dataset_dir / filename
        _write_jsonl(path, split_rows)
        dataset_info[f"{dataset_prefix}_{split}"] = {
            "file_name": filename,
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
            },
        }
        files[filename] = {"records": len(split_rows), "sha256": sha256_file(path)}
    info_path = dataset_dir / "dataset_info.json"
    _write_json(info_path, dataset_info)
    manifest = {
        "schema_version": "studyhub.agent.sft.controlled_v2.variant.v1",
        "task": task,
        "variant": variant,
        "source_sha256": source_sha256,
        "assistant_only_loss": True,
        "train_on_prompt": False,
        "template": "qwen3_5_nothink",
        "split_counts": {
            split: len(values) for split, values in sorted(by_split.items())
        },
        "family_counts": dict(
            sorted(Counter(str(row["task_family"]) for row in rows).items())
        ),
        "design": dict(design),
        "files": files,
        "dataset_info_sha256": sha256_file(info_path),
    }
    _write_json(variant_dir / "manifest.json", manifest)
    return manifest


def build_router_variants(
    *, paths: ControlledPaths | None = None, seed: int = 7703
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    source = load_jsonl(paths.router_source)
    train = [row for row in source if row["split"] == "train"]
    validation = [copy.deepcopy(row) for row in source if row["split"] == "validation"]
    source_hash = sha256_file(paths.router_source)
    manifests: dict[str, Any] = {}

    for fraction in ROUTER_DATA_FRACTIONS:
        variant = f"data_{round(fraction * 100):03d}pct"
        selected = _stratified_fraction(train, fraction, seed=seed)
        manifests[variant] = _export_sharegpt(
            rows=[*selected, *validation],
            variant_dir=paths.training_root / "datasets/router" / variant,
            task="router",
            variant=variant,
            source_sha256=source_hash,
            design={
                "factor": "training_data_fraction",
                "fraction": fraction,
                "fixed_optimizer_steps": ROUTER_FIXED_OPTIMIZER_STEPS,
                "sampling": "task_family_x_runtime_path_stratified",
            },
        )

    replay_pool = [row for row in train if "replay" in str(row["task_family"])]
    new_pool = [row for row in train if row not in replay_pool]
    total = len(train)
    for ratio in ROUTER_REPLAY_RATIOS:
        replay_count = round(total * ratio)
        new_count = total - replay_count
        selected = [
            *_balanced_sample(replay_pool, replay_count, seed=seed + 11),
            *_balanced_sample(new_pool, new_count, seed=seed + 13),
        ]
        variant = f"replay_{round(ratio * 100):02d}pct"
        manifests[variant] = _export_sharegpt(
            rows=[*selected, *validation],
            variant_dir=paths.training_root / "datasets/router" / variant,
            task="router",
            variant=variant,
            source_sha256=source_hash,
            design={
                "factor": "replay_ratio",
                "ratio": ratio,
                "replacement_not_append": True,
                "total_train_records": total,
                "fixed_optimizer_steps": ROUTER_FIXED_OPTIMIZER_STEPS,
            },
        )

    for state in ROUTER_STATE_VARIANTS:
        if state == "mixed":
            selected = [copy.deepcopy(row) for row in train]
        else:
            pool = [
                row
                for row in train
                if str((row.get("remediation_contract") or {}).get("runtime_path"))
                == state
            ]
            selected = _balanced_sample(pool, total, seed=seed + 17)
        variant = f"state_{state}"
        manifests[variant] = _export_sharegpt(
            rows=[*selected, *validation],
            variant_dir=paths.training_root / "datasets/router" / variant,
            task="router",
            variant=variant,
            source_sha256=source_hash,
            design={
                "factor": "state_representation",
                "state": state,
                "total_train_records": total,
                "fixed_optimizer_steps": ROUTER_FIXED_OPTIMIZER_STEPS,
            },
        )
    _write_json(paths.training_root / "datasets/router/variant_index.json", manifests)
    return manifests


def _negative_pool(
    rows: Sequence[Mapping[str, Any]], *, split: str
) -> dict[str, list[dict[str, Any]]]:
    split_rows = [row for row in rows if row["split"] == split]
    page_rows = _page_evidence_rows(split_rows)
    if len(page_rows) < 2:
        raise ValueError(f"Tutor {split} split lacks page-evidence rows")
    no_answer = [
        copy.deepcopy(row)
        for row in split_rows
        if str(row["task_family"])
        in {"insufficient_evidence_v1", "unsupported_claim_correction_v1"}
    ]
    untrusted = [
        copy.deepcopy(row)
        for row in split_rows
        if str(row["task_family"]) == "untrusted_observation_v1"
    ]
    conflicts: list[dict[str, Any]] = []
    for index, source in enumerate(page_rows):
        distractor = page_rows[(index * 7 + 1) % len(page_rows)]
        if distractor["example_id"] == source["example_id"]:
            distractor = page_rows[(index + 1) % len(page_rows)]
        generated = _pressure_case(
            source,
            distractor,
            family="conflict_v2",
            example_id=f"9b_{8000 + index:04d}",
            item_index=index,
            split=split,
        )
        generated["training_eligible"] = True
        generated["task_family"] = "controlled_conflict_mix_v2"
        conflicts.append(generated)
    return {"no_answer": no_answer, "conflict": conflicts, "untrusted": untrusted}


def build_tutor_mix_variants(
    *, paths: ControlledPaths | None = None, seed: int = 6209
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    source = load_jsonl(paths.tutor_source)
    source_hash = sha256_file(paths.tutor_source)
    manifests: dict[str, Any] = {}
    negative_families = {
        "insufficient_evidence_v1",
        "unsupported_claim_correction_v1",
        "untrusted_observation_v1",
    }
    for ratio in TUTOR_NEGATIVE_RATIOS:
        built: list[dict[str, Any]] = []
        class_counts: dict[str, dict[str, int]] = {}
        for split, total in (("train", 960), ("validation", 120)):
            split_rows = [row for row in source if row["split"] == split]
            positive_pool = [
                row
                for row in split_rows
                if str(row["task_family"]) not in negative_families
            ]
            pools = _negative_pool(source, split=split)
            negative_total = round(total * ratio)
            base, remainder = divmod(negative_total, len(pools))
            targets = {
                name: base + (1 if index < remainder else 0)
                for index, name in enumerate(sorted(pools))
            }
            negatives = [
                row
                for index, (name, pool) in enumerate(sorted(pools.items()))
                for row in _balanced_sample(
                    pool,
                    targets[name],
                    seed=seed + index + (0 if split == "train" else 100),
                )
            ]
            positives = _balanced_sample(
                positive_pool,
                total - negative_total,
                seed=seed + (31 if split == "train" else 131),
            )
            built.extend([*positives, *negatives])
            class_counts[split] = targets | {"positive": len(positives)}
        variant = f"negative_{round(ratio * 100):02d}pct"
        manifests[variant] = _export_sharegpt(
            rows=built,
            variant_dir=paths.training_root / "datasets/tutor" / variant,
            task="tutor",
            variant=variant,
            source_sha256=source_hash,
            design={
                "factor": "negative_evidence_ratio",
                "ratio": ratio,
                "total_records": 1080,
                "split_counts": {"train": 960, "validation": 120},
                "negative_classes": class_counts,
                "fixed_optimizer_steps": TUTOR_FIXED_OPTIMIZER_STEPS,
            },
        )
    _write_json(paths.training_root / "datasets/tutor/variant_index.json", manifests)
    return manifests


def router_data_experiments(winner: ExperimentSpec) -> tuple[ExperimentSpec, ...]:
    result: list[ExperimentSpec] = []
    for fraction in ROUTER_DATA_FRACTIONS:
        label = round(fraction * 100)
        result.append(
            ExperimentSpec(
                experiment_id=f"r-data-scale-{label:03d}pct",
                task="router",
                seed=7703,
                learning_rate=winner.learning_rate,
                epochs=winner.epochs,
                lora_rank=winner.lora_rank,
                lora_target=winner.lora_target,
                scheduler=winner.scheduler,
                dataset_variant=f"data_{label:03d}pct",
                max_steps=ROUTER_FIXED_OPTIMIZER_STEPS,
                stage="r-data-scale",
                parent_experiment_id=winner.experiment_id,
            )
        )
    for ratio in ROUTER_REPLAY_RATIOS:
        label = round(ratio * 100)
        result.append(
            ExperimentSpec(
                experiment_id=f"r-data-replay-{label:02d}pct",
                task="router",
                seed=7703,
                learning_rate=winner.learning_rate,
                epochs=winner.epochs,
                lora_rank=winner.lora_rank,
                lora_target=winner.lora_target,
                scheduler=winner.scheduler,
                dataset_variant=f"replay_{label:02d}pct",
                max_steps=ROUTER_FIXED_OPTIMIZER_STEPS,
                stage="r-data-replay",
                parent_experiment_id=winner.experiment_id,
            )
        )
    for state in ROUTER_STATE_VARIANTS:
        result.append(
            ExperimentSpec(
                experiment_id=f"r-data-state-{state}",
                task="router",
                seed=7703,
                learning_rate=winner.learning_rate,
                epochs=winner.epochs,
                lora_rank=winner.lora_rank,
                lora_target=winner.lora_target,
                scheduler=winner.scheduler,
                dataset_variant=f"state_{state}",
                max_steps=ROUTER_FIXED_OPTIMIZER_STEPS,
                stage="r-data-state",
                parent_experiment_id=winner.experiment_id,
            )
        )
    return tuple(result)


def tutor_mix_experiments(winner: ExperimentSpec) -> tuple[ExperimentSpec, ...]:
    return tuple(
        ExperimentSpec(
            experiment_id=f"t-mix-negative-{round(ratio * 100):02d}pct",
            task="tutor",
            seed=6209,
            learning_rate=winner.learning_rate,
            epochs=winner.epochs,
            lora_rank=winner.lora_rank,
            lora_target=winner.lora_target,
            scheduler=winner.scheduler,
            dataset_variant=f"negative_{round(ratio * 100):02d}pct",
            max_steps=TUTOR_FIXED_OPTIMIZER_STEPS,
            stage="t-mix",
            parent_experiment_id=winner.experiment_id,
        )
        for ratio in TUTOR_NEGATIVE_RATIOS
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task", choices=("router", "tutor", "all"), default="all", nargs="?"
    )
    args = parser.parse_args()
    result: dict[str, Any] = {}
    if args.task in {"router", "all"}:
        result["router"] = build_router_variants()
    if args.task in {"tutor", "all"}:
        result["tutor"] = build_tutor_mix_variants()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
