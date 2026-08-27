#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from studyhub_agent.benchmark_v2.challenge_suite import build_challenge_results, grade_challenge_results
from studyhub_agent.benchmark_v2.schema import BENCHMARK_VERSION


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=project / "artifacts/benchmark-v2/studyhub-agent-v2",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "artifacts/benchmark-v2/self-tests/evaluator-challenge-report.json",
    )
    parser.add_argument(
        "--public-summary",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/evaluator-challenge-summary.json",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    report = grade_challenge_results(await build_challenge_results(args.hidden_root.resolve()))
    report.update(
        {
            "schema_version": "studyhub.agentbench-evaluator-challenge.v2",
            "benchmark_version": BENCHMARK_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "schema_version": report["schema_version"],
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": report["generated_at"],
        "status": report["status"],
        **report["summary"],
        "artifact_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.public_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
