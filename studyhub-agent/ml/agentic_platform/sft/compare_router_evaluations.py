"""Rescore saved router predictions and compare base and adapter runs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .build_validation_dataset import DEFAULT_OUTPUT_DIR
from .evaluate_router import _score
from .spec import load_jsonl


DEFAULT_EVALUATION_DIR = DEFAULT_OUTPUT_DIR / "evaluation"
METRICS = (
    "json_valid",
    "contract_valid",
    "mode_correct",
    "tool_name_correct",
    "arguments_exact",
)


def _summarize(path: Path) -> dict[str, Any]:
    rows = load_jsonl(path)
    totals: Counter[str] = Counter()
    family_totals: dict[str, Counter[str]] = defaultdict(Counter)
    family_sizes: Counter[str] = Counter()
    refusal_total = 0
    refusal_passed = 0
    for row in rows:
        scores = _score(dict(row["expected"]), row.get("parsed"))
        family = str(row["task_family"])
        family_sizes[family] += 1
        for metric, passed in scores.items():
            totals[metric] += int(passed)
            family_totals[family][metric] += int(passed)
        if family == "refuse_permission_bypass":
            refusal_total += 1
            refusal_passed += int(scores["policy_refusal"])

    count = len(rows)
    return {
        "predictions_path": str(path),
        "records": count,
        "metrics": {
            metric: {
                "passed": totals[metric],
                "total": count,
                "rate": round(totals[metric] / count, 6),
            }
            for metric in METRICS
        },
        "policy_refusal": {
            "passed": refusal_passed,
            "total": refusal_total,
            "rate": round(refusal_passed / refusal_total, 6)
            if refusal_total
            else None,
        },
        "family_metrics": {
            family: {
                metric: {
                    "passed": counts[metric],
                    "total": family_sizes[family],
                    "rate": round(counts[metric] / family_sizes[family], 6),
                }
                for metric in METRICS
            }
            for family, counts in sorted(family_totals.items())
        },
    }


def compare_evaluations(
    *,
    evaluation_dir: Path = DEFAULT_EVALUATION_DIR,
    output_path: Path | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"splits": {}}
    for split in ("validation", "test"):
        split_dir = evaluation_dir / split
        base = _summarize(split_dir / "base_predictions.jsonl")
        adapter = _summarize(split_dir / "adapter_predictions.jsonl")
        result["splits"][split] = {
            "base": base,
            "adapter": adapter,
            "delta_rate": {
                metric: round(
                    adapter["metrics"][metric]["rate"]
                    - base["metrics"][metric]["rate"],
                    6,
                )
                for metric in METRICS
            },
        }

    destination = output_path or evaluation_dir / "comparison.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, default=DEFAULT_EVALUATION_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare_evaluations(
        evaluation_dir=args.evaluation_dir,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
