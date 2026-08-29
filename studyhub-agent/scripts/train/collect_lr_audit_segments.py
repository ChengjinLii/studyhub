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
    attempts: list[tuple[int, Path, str, int]] = []
    for metadata_path in sorted(log_root.glob(f"{attempt_prefix}-attempt-*.run.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        overrides = _override_map(metadata)
        if "studyhub_attempt_start_step" not in overrides:
            continue
        start = int(overrides["studyhub_attempt_start_step"])
        attempt_id = metadata_path.name.removesuffix(".run.json")
        metrics = evidence_root / attempt_id / "metrics" / "trainer.json"
        if metrics.is_file():
            payload = json.loads(metrics.read_text(encoding="utf-8"))
            observed = len(payload.get("series", {}).get("sft/lr", []))
            attempts.append((start, metrics, attempt_id, observed))
    if not attempts:
        raise RuntimeError(f"no LR metric attempts found for {attempt_prefix}")

    by_start: dict[int, list[tuple[Path, str, int]]] = {}
    for start, metrics, attempt_id, observed in attempts:
        by_start.setdefault(start, []).append((metrics, attempt_id, observed))
    starts = sorted(by_start)
    if starts[0] != 0:
        raise RuntimeError(f"first attempt does not start at zero: {starts[0]}")

    segments: list[tuple[Path, int, int]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else expected_updates
        count = end - start
        if count <= 0:
            raise RuntimeError(f"invalid durable segment: {start}..{end}")
        eligible = [candidate for candidate in by_start[start] if candidate[2] >= count]
        if not eligible:
            observed = max(candidate[2] for candidate in by_start[start])
            raise RuntimeError(
                f"attempt at step {start} has {observed} LR points but {count} are required"
            )
        if len(eligible) != 1:
            attempt_ids = sorted(candidate[1] for candidate in eligible)
            raise RuntimeError(
                f"ambiguous durable attempts at step {start}: {attempt_ids}"
            )
        metrics, _, _ = eligible[0]
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
