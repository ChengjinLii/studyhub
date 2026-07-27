#!/usr/bin/env python3
"""Run a bounded, provider-agnostic Agent pilot from a scenario manifest."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
for import_root in (ROOT_DIR / "backend", ROOT_DIR):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)

from ml.agentic_platform.collection.pilot import (  # noqa: E402
    PilotConfigurationError,
    load_pilot_manifest,
    run_pilot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded Agent pilot through the manifest's trusted local runner plugin."
    )
    parser.add_argument("--scenario-manifest", required=True, help="JSON PilotScenarioManifest path")
    parser.add_argument("--count", required=True, type=int, help="Number of manifest scenarios to run")
    parser.add_argument("--concurrency", required=True, type=int, help="Maximum concurrent scenario runners")
    parser.add_argument("--provider", required=True, help="Provider label passed unchanged to the runner plugin")
    parser.add_argument("--output-dir", required=True, help="Directory for pilot-run.json")
    parser.add_argument("--resume", action="store_true", help="Reuse completed outcomes from output-dir/pilot-run.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_pilot_manifest(args.scenario_manifest)
        report = asyncio.run(
            run_pilot(
                manifest,
                count=args.count,
                concurrency=args.concurrency,
                provider=args.provider,
                output_dir=args.output_dir,
                resume=args.resume,
            )
        )
    except PilotConfigurationError as exc:
        print(f"agentic-pilot: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "pilotReport": str(Path(args.output_dir) / "pilot-run.json"),
                "requestedCount": report.requested_count,
                "completed": sum(outcome.status.value == "completed" for outcome in report.outcomes),
                "contentHash": report.content_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
