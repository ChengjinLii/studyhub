#!/usr/bin/env python3
"""Audit initial RL prompts with the exact pinned AReaL HF render path."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.rl.frozen_environment import FrozenTaskEnvironment
from training.rl.hermes_workflow import SYSTEM_PROMPT, _request_token_count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _distribution(values: list[int]) -> dict[str, int | float]:
    if not values:
        raise ValueError("cannot summarize an empty distribution")
    return {
        "min": min(values),
        "mean": round(statistics.fmean(values), 3),
        "p50": round(statistics.median(values), 3),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values),
    }


def _openai_tools(environment: FrozenTaskEnvironment) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": schema}
        for schema in environment.tool_schemas
    ]


def audit(
    *,
    dataset_root: Path,
    tokenizer_path: Path,
    engine_max_tokens: int,
    finalization_ratio: float,
    safety_margin_tokens: int,
) -> dict[str, Any]:
    from areal.utils.hf_utils import load_hf_tokenizer

    tokenizer = load_hf_tokenizer(str(tokenizer_path))
    threshold = int(engine_max_tokens * finalization_ratio)
    safe_target = engine_max_tokens - safety_margin_tokens
    rows: list[dict[str, Any]] = []
    by_family: dict[str, list[int]] = defaultdict(list)
    split_hashes: dict[str, str] = {}

    for split in ("train", "validation"):
        task_path = dataset_root / "tasks" / f"{split}.jsonl"
        split_hashes[split] = _sha256(task_path)
        for task in _load_jsonl(task_path):
            environment = FrozenTaskEnvironment.from_root(
                dataset_root,
                str(task["task_id"]),
                max_tool_calls=int(task["max_tool_calls"]),
            )
            count = _request_token_count(
                tokenizer,
                {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": str(task["user_request"])},
                    ],
                    "tools": _openai_tools(environment),
                },
            )
            family = str(task["family"])
            by_family[family].append(count)
            rows.append(
                {
                    "task_id": str(task["task_id"]),
                    "split": split,
                    "family": family,
                    "prompt_tokens": count,
                    "tool_count": len(environment.tool_schemas),
                }
            )

    values = [int(row["prompt_tokens"]) for row in rows]
    largest = sorted(rows, key=lambda row: (-int(row["prompt_tokens"]), row["task_id"]))[:10]
    result = {
        "schema_version": "studyhub.initial-context-budget-audit.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "initial request only; multi-turn growth is measured by runtime telemetry",
        "dataset_root": str(dataset_root.resolve()),
        "dataset_manifest_sha256": _sha256(dataset_root / "manifest.json"),
        "task_split_sha256": split_hashes,
        "tokenizer_path": str(tokenizer_path.resolve()),
        "tokenizer_config_sha256": _sha256(tokenizer_path / "tokenizer_config.json"),
        "render_contract": "pinned AReaL hf chat template with SGLang-aligned tools",
        "policy": {
            "engine_max_tokens": engine_max_tokens,
            "finalization_ratio": finalization_ratio,
            "finalization_threshold_tokens": threshold,
            "safety_margin_tokens": safety_margin_tokens,
            "safe_target_tokens": safe_target,
        },
        "tasks": len(rows),
        "distribution": _distribution(values),
        "by_family": {
            family: {"tasks": len(family_values), **_distribution(family_values)}
            for family, family_values in sorted(by_family.items())
        },
        "threshold_counts": {
            "at_or_above_finalization_threshold": sum(value >= threshold for value in values),
            "above_safe_target": sum(value > safe_target for value in values),
            "at_or_above_engine_limit": sum(
                value >= engine_max_tokens for value in values
            ),
        },
        "largest_initial_prompts": largest,
    }
    result["status"] = (
        "passed"
        if result["threshold_counts"]["at_or_above_finalization_threshold"] == 0
        else "failed"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/open_agent_rl_v2",
    )
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--engine-max-tokens", type=int, default=4096)
    parser.add_argument("--finalization-ratio", type=float, default=0.80)
    parser.add_argument("--safety-margin-tokens", type=int, default=256)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = audit(
        dataset_root=args.dataset_root,
        tokenizer_path=args.tokenizer,
        engine_max_tokens=args.engine_max_tokens,
        finalization_ratio=args.finalization_ratio,
        safety_margin_tokens=args.safety_margin_tokens,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
