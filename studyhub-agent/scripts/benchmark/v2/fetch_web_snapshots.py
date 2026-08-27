#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from studyhub_agent.benchmark_v2.web_snapshot import fetch_snapshot, validate_offline_snapshot


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=project / "configs/benchmark-v2-web-sources.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "artifacts/benchmark-v2/web-snapshots/snapshot.jsonl",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=project / "configs/benchmark-v2-web-lock.json",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh-lock", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.offline:
        result = validate_offline_snapshot(
            config_path=args.config.resolve(),
            output_path=args.output.resolve(),
            lock_path=args.lock.resolve(),
        )
    else:
        result = fetch_snapshot(
            config_path=args.config.resolve(),
            output_path=args.output.resolve(),
            lock_path=args.lock.resolve(),
            refresh_lock=args.refresh_lock,
            workers=args.workers,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
