from __future__ import annotations

import argparse
from pathlib import Path

from app.contracts.executor import build_httpx_executor
from app.contracts.loader import load_contract_samples
from app.contracts.runner import ContractSuiteRunner
from app.core.config import get_settings


def main() -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Run StudyHub contract diff samples")
    parser.add_argument("--candidate-base-url", required=True, help="FastAPI target base URL")
    parser.add_argument("--baseline-base-url", help="Optional baseline Java target base URL")
    parser.add_argument(
        "--sample-dir",
        default=str(settings.resolved_contract_sample_dir),
        help="Contract sample directory",
    )
    parser.add_argument(
        "--output-dir",
        default=str(settings.resolved_contract_report_dir),
        help="Diff report output directory",
    )
    parser.add_argument(
        "--sample-id",
        action="append",
        dest="sample_ids",
        help="Only run the given sample id, can be repeated",
    )
    args = parser.parse_args()

    sample_dir = Path(args.sample_dir)
    output_dir = Path(args.output_dir)
    selected_ids = set(args.sample_ids or [])
    samples = load_contract_samples(sample_dir, selected_ids or None)
    if not samples:
        raise SystemExit("No contract samples found.")

    candidate_client, candidate_executor = build_httpx_executor(args.candidate_base_url)
    baseline_client = None
    baseline_executor = None
    if args.baseline_base_url:
        baseline_client, baseline_executor = build_httpx_executor(args.baseline_base_url)

    try:
        summary = ContractSuiteRunner().run(
            samples=samples,
            candidate_executor=candidate_executor,
            baseline_executor=baseline_executor,
            output_dir=output_dir,
        )
    finally:
        candidate_client.close()
        if baseline_client is not None:
            baseline_client.close()

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
