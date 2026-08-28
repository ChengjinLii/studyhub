#!/usr/bin/env python3
"""Collect durable LR metric segments across attempts of one resumed SFT trial."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _override_map(metadata: dict[str, Any]) -> dict[str, str]:
    result = {}
    for value in metadata.get("config", {}).get("overrides", []):
        key, separator, item = str(value).partition("=")
        if separator:
            result[key] = item
    return result


def collect(
    log_root: Path,
    evidence_root: Path,
    *,
    attempt_prefix: str,
    expected_updates: int,
) -> list[tuple[Path, int, int]]:
    attempts: list[tuple[int, Path, str]] = []
    for metadata_path in sorted(log_root.glob(f"{attempt_prefix}-attempt-*.run.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        overrides = _override_map(metadata)
        if "studyhub_attempt_start_step" not in overrides:
            continue
        start = int(overrides["studyhub_attempt_start_step"])
        attempt_id = metadata_path.name.removesuffix(".run.json")
        metrics = evidence_root / attempt_id / "metrics" / "trainer.json"
        if metrics.is_file():
            attempts.append((start, metrics, attempt_id))
    if not attempts:
        raise RuntimeError(f"no LR metric attempts found for {attempt_prefix}")

    attempts.sort(key=lambda value: value[0])
    starts = [start for start, _, _ in attempts]
    if len(starts) != len(set(starts)):
        raise RuntimeError(f"duplicate attempt start steps: {starts}")
    if starts[0] != 0:
        raise RuntimeError(f"first attempt does not start at zero: {starts[0]}")

    segments: list[tuple[Path, int, int]] = []
    for index, (start, metrics, attempt_id) in enumerate(attempts):
        end = starts[index + 1] if index + 1 < len(starts) else expected_updates
        count = end - start
        if count <= 0:
            raise RuntimeError(f"invalid durable segment for {attempt_id}: {start}..{end}")
        payload = json.loads(metrics.read_text(encoding="utf-8"))
        observed = len(payload.get("series", {}).get("sft/lr", []))
        if observed < count:
            raise RuntimeError(
                f"attempt {attempt_id} has {observed} LR points but {count} are required"
            )
        segments.append((metrics, start, count))
    return segments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--attempt-prefix", required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    segments = collect(
        args.log_root,
        args.evidence_root,
        attempt_prefix=args.attempt_prefix,
        expected_updates=args.expected_updates,
    )
    payload = {
        "schema_version": "studyhub.sft-lr-segment-index.v1",
        "status": "PASS",
        "attempt_prefix": args.attempt_prefix,
        "expected_updates": args.expected_updates,
        "segments": [
            {"metrics": str(path), "start_global_step": start, "count": count}
            for path, start, count in segments
        ],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    for path, start, count in segments:
        print(f"{path},{start},{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
