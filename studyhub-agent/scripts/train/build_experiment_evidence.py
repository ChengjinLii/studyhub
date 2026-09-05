#!/usr/bin/env python3
"""Build a compact, reproducible evidence bundle for one AReaL trial."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts.train.summarize_reward_groups import summarize as summarize_rewards
except ModuleNotFoundError:  # Direct execution adds scripts/train, not the repo root.
    from summarize_reward_groups import summarize as summarize_rewards


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
USER_MESSAGE = re.compile(
    r"<\|im_start\|>user\n(.*?)<\|im_end\|>",
    re.DOTALL,
)
SYSTEM_PROMPT_MARKER = "You are StudyHub Agent in an isolated training environment."
GLOBAL_STEP = re.compile(r"globalstep(\d+)")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_metric_series(log_text: str) -> dict[str, list[float]]:
    """Extract every numeric metric from AReaL's Unicode StatsLogger tables."""

    series: dict[str, list[float]] = defaultdict(list)
    clean_text = ANSI_ESCAPE.sub("", log_text)
    for line in clean_text.splitlines():
        if not line.startswith("│"):
            continue
        cells = [cell.strip() for cell in line.split("│")[1:-1]]
        for index in range(0, len(cells) - 1, 2):
            metric, raw_value = cells[index : index + 2]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./-]*", metric):
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if math.isfinite(value):
                series[metric].append(value)
    return dict(sorted(series.items()))


def summarize_metric_series(series: dict[str, list[float]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for metric, values in series.items():
        if not values:
            continue
        summary[metric] = {
            "count": len(values),
            "first": values[0],
            "last": values[-1],
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
        }
    return summary


def summarize_gpu_csv(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"samples": 0}
    with path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    by_gpu: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"memory_used_mib": [], "utilization_gpu_pct": []})
    for row in rows:
        gpu = str(row.get("gpu_index", row.get("index", "unknown")))
        for key in ("memory_used_mib", "utilization_gpu_pct"):
            raw = row.get(key)
            if raw not in (None, ""):
                by_gpu[gpu][key].append(float(raw))
    return {
        "samples": len(rows),
        "per_gpu": {
            gpu: {
                "peak_memory_used_mib": max(values["memory_used_mib"], default=None),
                "mean_memory_used_mib": (
                    statistics.fmean(values["memory_used_mib"]) if values["memory_used_mib"] else None
                ),
                "peak_utilization_gpu_pct": max(values["utilization_gpu_pct"], default=None),
                "mean_utilization_gpu_pct": (
                    statistics.fmean(values["utilization_gpu_pct"]) if values["utilization_gpu_pct"] else None
                ),
            }
            for gpu, values in sorted(by_gpu.items())
        },
    }


def checkpoint_index(root: Path | None) -> list[dict[str, Any]]:
    if root is None or not root.is_dir():
        return []
    indexed = []
    for path in sorted(root.rglob("adapter_model.safetensors")):
        step_match = GLOBAL_STEP.search(str(path))
        indexed.append(
            {
                "path": str(path.resolve()),
                "relative_path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "global_step": int(step_match.group(1)) if step_match else None,
            }
        )
    return indexed


def summarize_lora_immutability(checkpoints: list[dict[str, Any]], *, required: bool) -> dict[str, Any]:
    initial = next(
        (row for row in checkpoints if row["relative_path"] == "actor/initial_lora/adapter_model.safetensors"),
        None,
    )
    trained = [row for row in checkpoints if row.get("global_step") is not None]
    final = max(trained, key=lambda row: int(row["global_step"])) if trained else None
    unchanged = bool(initial and final and initial["sha256"] == final["sha256"])
    update_observed = bool(initial and final and initial["sha256"] != final["sha256"])
    return {
        "schema_version": "studyhub.lora-immutability.v1",
        "required": required,
        "initial": initial,
        "final": final,
        "unchanged": unchanged,
        "update_observed": update_observed,
        "comparison_status": (
            "unchanged"
            if unchanged
            else "updated"
            if update_observed
            else "initial_missing"
            if initial is None
            else "final_missing"
        ),
        "status": ("passed" if required and unchanged else "failed" if required else "diagnostic"),
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _load_task_lookup(task_root: Path | None) -> tuple[dict[str, dict[str, Any]], int]:
    if task_root is None or not task_root.exists():
        return {}, 0
    task_paths = [task_root] if task_root.is_file() else sorted(task_root.glob("*.jsonl"))
    by_request: dict[str, dict[str, Any]] = {}
    collisions = 0
    for path in task_paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                request = str(row.get("user_request", row.get("goal", "")))
                if not request:
                    continue
                if request in by_request and by_request[request]["task_id"] != row["task_id"]:
                    collisions += 1
                    continue
                by_request[request] = row
    return by_request, collisions


def index_rollout_interactions(
    root: Path | None,
    *,
    task_root: Path | None,
    trial: str,
    run_seed: int | None,
    max_sequence_tokens: int,
    system_prompt_marker: str = SYSTEM_PROMPT_MARKER,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """Index AReaL's raw interaction dumps without copying prompt contents."""

    if root is None or not root.is_dir():
        return [], [], None
    task_lookup, request_collisions = _load_task_lookup(task_root)
    file_rows: list[dict[str, Any]] = []
    record_rows: list[dict[str, Any]] = []
    sequence_lengths: list[float] = []
    prompt_lengths: list[float] = []
    completion_lengths: list[float] = []
    rewards: list[float] = []
    versions: dict[str, int] = defaultdict(int)
    mapped_tasks: set[str] = set()
    unmapped_files = 0
    mixed_policy_records = 0
    truncated_records = 0
    duplicated_system_prompt_records = 0
    missing_system_prompt_records = 0

    def path_key(path: Path) -> tuple[int, str]:
        try:
            version = int(path.parent.name)
        except ValueError:
            version = 2**31 - 1
        return version, str(path)

    for path in sorted(root.glob("*/*.jsonl"), key=path_key):
        relative = str(path.relative_to(root))
        raw_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        rows = [json.loads(line) for line in raw_lines]
        prompt = str(rows[0].get("prompt", "")) if rows else ""
        user_match = USER_MESSAGE.search(prompt)
        user_request = user_match.group(1) if user_match else ""
        task = task_lookup.get(user_request)
        if task is None:
            unmapped_files += 1
        else:
            mapped_tasks.add(str(task["task_id"]))
        file_rows.append(
            {
                "path": str(path.resolve()),
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "record_count": len(rows),
                "internal_task_id": rows[0].get("task_id") if rows else None,
                "task_id": task.get("task_id") if task else None,
                "policy_version_directory": path.parent.name,
            }
        )
        for line_number, row in enumerate(rows, start=1):
            sequence_length = int(row.get("seqlen", 0))
            prompt_length = int(row.get("prompt_len", 0))
            completion_length = max(0, sequence_length - prompt_length)
            head_version = int(row.get("head_version", -1))
            tail_version = int(row.get("tail_version", -1))
            if head_version != tail_version:
                mixed_policy_records += 1
            if sequence_length >= max_sequence_tokens:
                truncated_records += 1
            sequence_lengths.append(float(sequence_length))
            prompt_lengths.append(float(prompt_length))
            completion_lengths.append(float(completion_length))
            reward = float(row.get("reward", 0.0))
            rewards.append(reward)
            versions[str(tail_version)] += 1
            system_prompt_count = str(row.get("prompt", "")).count(system_prompt_marker)
            if system_prompt_count == 0:
                missing_system_prompt_records += 1
            elif system_prompt_count > 1:
                duplicated_system_prompt_records += 1
            record_rows.append(
                {
                    "record_id": hashlib.sha256(f"{trial}:{relative}:{line_number}".encode()).hexdigest()[:24],
                    "trial": trial,
                    "source_file": relative,
                    "line_number": line_number,
                    "internal_task_id": row.get("task_id"),
                    "task_id": task.get("task_id") if task else None,
                    "task_family": task.get("family", task.get("metadata", {}).get("family")) if task else None,
                    "source_dataset": (task.get("metadata", {}).get("source_dataset") if task else None),
                    "split": task.get("metadata", {}).get("split") if task else None,
                    "run_seed": run_seed,
                    "environment_seed": task.get("environment_seed") if task else None,
                    "rollout_seed": None,
                    "sample_idx": row.get("sample_idx"),
                    "head_policy_version": head_version,
                    "tail_policy_version": tail_version,
                    "policy_version_rle": row.get("version_rle", []),
                    "trajectory_reuse_count": 1,
                    "sequence_tokens": sequence_length,
                    "prompt_tokens": prompt_length,
                    "completion_tokens": completion_length,
                    "at_sequence_limit": sequence_length >= max_sequence_tokens,
                    "system_prompt_marker_count": system_prompt_count,
                    "reward": reward,
                    "prompt_sha256": hashlib.sha256(str(row.get("prompt", "")).encode()).hexdigest(),
                    "completion_sha256": hashlib.sha256(str(row.get("completion", "")).encode()).hexdigest(),
                }
            )

    summary = {
        "schema_version": "studyhub.rollout-interaction-summary.v1",
        "trial": trial,
        "raw_root": str(root.resolve()),
        "files": len(file_rows),
        "exported_interactions": len(record_rows),
        "mapped_tasks": len(mapped_tasks),
        "unmapped_files": unmapped_files,
        "task_request_collisions": request_collisions,
        "policy_version_counts": dict(sorted(versions.items(), key=lambda item: int(item[0]))),
        "mixed_policy_records": mixed_policy_records,
        "system_prompt_integrity": {
            "marker": system_prompt_marker,
            "missing_records": missing_system_prompt_records,
            "duplicated_records": duplicated_system_prompt_records,
            "all_records_exactly_once": (
                bool(record_rows) and missing_system_prompt_records == 0 and duplicated_system_prompt_records == 0
            ),
        },
        "trajectory_reuse_count": 1,
        "rollout_seed_status": "not exposed by the pinned AReaL proxy workflow",
        "sequence_tokens": {
            "mean": statistics.fmean(sequence_lengths) if sequence_lengths else None,
            "p50": _percentile(sequence_lengths, 0.50),
            "p95": _percentile(sequence_lengths, 0.95),
            "max": max(sequence_lengths, default=None),
            "at_limit": truncated_records,
            "at_limit_rate": (truncated_records / len(sequence_lengths) if sequence_lengths else None),
            "limit": max_sequence_tokens,
        },
        "prompt_tokens": {
            "mean": statistics.fmean(prompt_lengths) if prompt_lengths else None,
            "p95": _percentile(prompt_lengths, 0.95),
            "max": max(prompt_lengths, default=None),
        },
        "completion_tokens": {
            "mean": statistics.fmean(completion_lengths) if completion_lengths else None,
            "p95": _percentile(completion_lengths, 0.95),
            "max": max(completion_lengths, default=None),
        },
        "interaction_reward": {
            "mean": statistics.fmean(rewards) if rewards else None,
            "min": min(rewards, default=None),
            "max": max(rewards, default=None),
        },
    }
    return file_rows, record_rows, summary


def _trial_from_metadata(path: Path) -> str:
    suffix = ".run.json"
    return path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    metadata_path = args.run_metadata.resolve()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    trial = _trial_from_metadata(metadata_path)
    output = (
        args.output.resolve()
        if args.output
        else (Path(metadata["project"]) / "artifacts" / "experiments" / trial).resolve()
    )
    output.mkdir(parents=True, exist_ok=True)

    log_path = Path(metadata["log_file"])
    gpu_path = Path(metadata["gpu_csv"])
    metric_series = (
        parse_metric_series(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.is_file() else {}
    )
    trainer_metrics = {
        "schema_version": "studyhub.trainer-metrics.v1",
        "trial": trial,
        "series": metric_series,
        "summary": summarize_metric_series(metric_series),
    }
    _write_json(output / "metrics" / "trainer.json", trainer_metrics)
    _write_json(output / "metrics" / "system.json", summarize_gpu_csv(gpu_path))

    reward_summary = None
    reward_log = None
    if args.reward_root:
        reward_log = (args.reward_root / "reward-v2.jsonl" if args.reward_root.is_dir() else args.reward_root).resolve()
        if reward_log.is_file() and reward_log.stat().st_size:
            reward_summary = summarize_rewards(reward_log, expected_group_size=args.expected_group_size)
            _write_json(output / "metrics" / "reward-groups.json", reward_summary)

    checkpoints = checkpoint_index(args.checkpoint_root)
    lora_immutability = summarize_lora_immutability(checkpoints, required=args.require_unchanged_lora)
    _write_json(output / "metrics" / "lora-immutability.json", lora_immutability)
    checkpoint_path = output / "checkpoints" / "checkpoint-index.jsonl"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in checkpoints),
        encoding="utf-8",
    )

    trajectory_files, trajectory_records, trajectory_summary = index_rollout_interactions(
        args.trajectory_root,
        task_root=args.task_root,
        trial=trial,
        run_seed=metadata.get("run_metadata", {}).get("seed") if "run_metadata" in metadata else None,
        max_sequence_tokens=args.max_sequence_tokens,
        system_prompt_marker=getattr(args, "system_prompt_marker", SYSTEM_PROMPT_MARKER),
    )
    # Run metadata stores the seed in the config overrides rather than a
    # top-level field. Preserve the configured seed when it can be recovered.
    if trajectory_records and all(row["run_seed"] is None for row in trajectory_records):
        seed = None
        for override in metadata.get("config", {}).get("overrides", []):
            if str(override).startswith("seed="):
                seed = int(str(override).split("=", 1)[1])
                break
        for row in trajectory_records:
            row["run_seed"] = seed
    trajectory_file_path = output / "trajectories" / "trajectory-files.jsonl"
    trajectory_record_path = output / "trajectories" / "trajectory-records.jsonl"
    if args.trajectory_root is not None:
        trajectory_file_path.parent.mkdir(parents=True, exist_ok=True)
        trajectory_file_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in trajectory_files),
            encoding="utf-8",
        )
        trajectory_record_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in trajectory_records),
            encoding="utf-8",
        )
        if trajectory_summary is not None:
            _write_json(output / "metrics" / "rollout-interactions.json", trajectory_summary)

    required = {
        "run_metadata": metadata_path.is_file(),
        "training_log": log_path.is_file(),
        "gpu_telemetry": gpu_path.is_file(),
        "trainer_metrics": bool(metric_series),
        "reward_log": reward_log is None or reward_log.is_file(),
        "reward_summary": reward_log is None or reward_summary is not None,
        "checkpoint_index": bool(checkpoints),
        "lora_unchanged": (not args.require_unchanged_lora or lora_immutability["unchanged"]),
        "trajectory_index": args.trajectory_root is None or bool(trajectory_records),
        "trajectory_task_mapping": (
            args.trajectory_root is None
            or (
                trajectory_summary is not None
                and trajectory_summary["unmapped_files"] == 0
                and trajectory_summary["task_request_collisions"] == 0
            )
        ),
        "exit_status_recorded": metadata.get("exit_status") is not None,
    }
    completeness = {
        "schema_version": "studyhub.artifact-completeness.v1",
        "trial": trial,
        "generated_at": _now(),
        "checks": required,
        "not_applicable": [
            name
            for name, applicable in {
                "reward_log": args.reward_root is not None,
                "reward_summary": args.reward_root is not None,
                "trajectory_index": args.trajectory_root is not None,
                "trajectory_task_mapping": args.trajectory_root is not None,
                "lora_unchanged": args.require_unchanged_lora,
            }.items()
            if not applicable
        ],
        "status": "COMPLETE" if all(required.values()) else "PARTIAL_EVIDENCE",
        "missing": [name for name, present in required.items() if not present],
    }
    _write_json(output / "artifact-completeness.json", completeness)

    manifest = {
        "schema_version": "studyhub.experiment-evidence.v1",
        "trial": trial,
        "generated_at": _now(),
        "evidence_tier": args.evidence_tier,
        "evidence_builder": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "run_metadata": metadata,
        "artifacts": {
            "source_run_metadata": str(metadata_path),
            "training_log": str(log_path.resolve()),
            "gpu_csv": str(gpu_path.resolve()),
            "reward_log": str(reward_log) if reward_log else None,
            "checkpoint_root": (str(args.checkpoint_root.resolve()) if args.checkpoint_root else None),
            "trainer_metrics": "metrics/trainer.json",
            "system_metrics": "metrics/system.json",
            "reward_summary": ("metrics/reward-groups.json" if reward_summary is not None else None),
            "checkpoint_index": "checkpoints/checkpoint-index.jsonl",
            "lora_immutability": "metrics/lora-immutability.json",
            "trajectory_root": (str(args.trajectory_root.resolve()) if args.trajectory_root else None),
            "trajectory_files": ("trajectories/trajectory-files.jsonl" if args.trajectory_root else None),
            "trajectory_records": ("trajectories/trajectory-records.jsonl" if args.trajectory_root else None),
            "trajectory_summary": ("metrics/rollout-interactions.json" if trajectory_summary else None),
        },
        "lora_immutability": lora_immutability,
        "completeness": completeness,
    }
    _write_json(output / "manifest.json", manifest)

    hash_targets = [
        Path(__file__).resolve(),
        metadata_path,
        log_path,
        gpu_path,
        output / "manifest.json",
        output / "artifact-completeness.json",
        output / "metrics" / "trainer.json",
        output / "metrics" / "system.json",
        output / "metrics" / "lora-immutability.json",
        checkpoint_path,
    ]
    if reward_log:
        hash_targets.append(reward_log)
    if reward_summary is not None:
        hash_targets.append(output / "metrics" / "reward-groups.json")
    if args.trajectory_root is not None:
        hash_targets.extend([trajectory_file_path, trajectory_record_path])
    if trajectory_summary is not None:
        hash_targets.append(output / "metrics" / "rollout-interactions.json")
    hash_lines = []
    for path in hash_targets:
        if path.is_file():
            hash_lines.append(f"{_sha256(path)}  {path.resolve()}\n")
    (output / "SHA256SUMS").write_text("".join(hash_lines), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--reward-root", type=Path)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--trajectory-root", type=Path)
    parser.add_argument("--task-root", type=Path)
    parser.add_argument("--max-sequence-tokens", type=int, default=4096)
    parser.add_argument("--system-prompt-marker", default=SYSTEM_PROMPT_MARKER)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-group-size", type=int, default=4)
    parser.add_argument("--require-unchanged-lora", action="store_true")
    parser.add_argument(
        "--evidence-tier",
        choices=("SCRATCH", "DIAGNOSTIC", "CLAIM"),
        default="DIAGNOSTIC",
    )
    args = parser.parse_args()
    if args.expected_group_size < 1:
        parser.error("--expected-group-size must be positive")
    if args.max_sequence_tokens < 1:
        parser.error("--max-sequence-tokens must be positive")
    if not args.system_prompt_marker.strip():
        parser.error("--system-prompt-marker must not be empty")
    return args


def main() -> int:
    args = parse_args()
    manifest = build_bundle(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if args.require_unchanged_lora and not manifest["lora_immutability"]["unchanged"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
