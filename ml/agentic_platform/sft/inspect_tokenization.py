"""Audit Qwen3.5 chat-template lengths before starting an SFT run."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from .build_validation_dataset import DEFAULT_OUTPUT_DIR
from .spec import load_jsonl


DEFAULT_MODEL = Path("/data/chengjin/studyhub/models/P0/Qwen3.5-2B")
DEFAULT_DATASET = DEFAULT_OUTPUT_DIR / "router_tool_2b.jsonl"
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "tokenization_report.json"


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _token_count(processor: Any, messages: list[dict[str, str]]) -> int:
    rendered = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    return len(processor.tokenizer(rendered, add_special_tokens=False)["input_ids"])


def inspect_tokenization(
    *,
    model_path: Path = DEFAULT_MODEL,
    dataset_path: Path = DEFAULT_DATASET,
    report_path: Path = DEFAULT_REPORT,
    cutoff_len: int = 4096,
) -> dict[str, Any]:
    from transformers import AutoProcessor

    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        local_files_only=True,
    )
    rows: list[dict[str, Any]] = []
    split_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    for record in load_jsonl(dataset_path):
        messages = [
            {"role": message["role"], "content": message["content"]}
            for message in record["messages"]
        ]
        prompt_tokens = _token_count(processor, messages[:-1])
        total_tokens = _token_count(processor, messages)
        target_tokens = total_tokens - prompt_tokens
        rows.append(
            {
                "example_id": record["example_id"],
                "split": record["split"],
                "task_family": record["task_family"],
                "prompt_tokens": prompt_tokens,
                "target_tokens": target_tokens,
                "total_tokens": total_tokens,
                "exceeds_cutoff": total_tokens > cutoff_len,
            }
        )
        split_counts[str(record["split"])] += 1
        family_counts[str(record["task_family"])] += 1

    total_lengths = [int(row["total_tokens"]) for row in rows]
    target_lengths = [int(row["target_tokens"]) for row in rows]
    invalid_targets = [
        str(row["example_id"]) for row in rows if int(row["target_tokens"]) <= 0
    ]
    over_cutoff = [
        str(row["example_id"]) for row in rows if bool(row["exceeds_cutoff"])
    ]
    result = {
        "model_path": str(model_path),
        "dataset_path": str(dataset_path),
        "template": "model chat_template with enable_thinking=false",
        "cutoff_len": cutoff_len,
        "records": len(rows),
        "split_counts": dict(sorted(split_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "total_tokens": {
            "min": min(total_lengths),
            "mean": round(statistics.fmean(total_lengths), 2),
            "p95": _percentile(total_lengths, 0.95),
            "max": max(total_lengths),
        },
        "target_tokens": {
            "min": min(target_lengths),
            "mean": round(statistics.fmean(target_lengths), 2),
            "p95": _percentile(target_lengths, 0.95),
            "max": max(target_lengths),
        },
        "over_cutoff_count": len(over_cutoff),
        "over_cutoff_example_ids": over_cutoff,
        "nonpositive_target_count": len(invalid_targets),
        "nonpositive_target_example_ids": invalid_targets,
        "passed": not over_cutoff and not invalid_targets,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cutoff-len", type=int, default=4096)
    args = parser.parse_args()
    result = inspect_tokenization(
        model_path=args.model,
        dataset_path=args.dataset,
        report_path=args.report,
        cutoff_len=args.cutoff_len,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
