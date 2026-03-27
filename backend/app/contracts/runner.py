from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.contracts.comparator import compare_snapshot, expectation_from_sample, expectation_from_snapshot
from app.contracts.models import ContractSample, SampleResult


class ContractSuiteRunner:
    def run(
        self,
        samples: list[ContractSample],
        candidate_executor,
        output_dir: Path,
        baseline_executor=None,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[SampleResult] = []

        for sample in samples:
            candidate_snapshot = candidate_executor.execute(sample)
            baseline_snapshot = baseline_executor.execute(sample) if baseline_executor else None
            expectation = (
                expectation_from_snapshot(baseline_snapshot)
                if baseline_snapshot is not None
                else expectation_from_sample(sample)
            )
            diffs = compare_snapshot(candidate_snapshot, expectation)
            results.append(
                SampleResult(
                    sample_id=sample.sample_id,
                    bundle=sample.bundle,
                    request_kind=sample.request_kind,
                    response_kind=sample.response_kind,
                    dimensions=_resolve_dimensions(sample),
                    passed=not diffs,
                    diffs=diffs,
                    candidate=candidate_snapshot,
                    baseline=baseline_snapshot,
                )
            )

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "baseline-http" if baseline_executor else "snapshot-baseline",
            "total": len(results),
            "passed": sum(1 for result in results if result.passed),
            "failed": sum(1 for result in results if not result.passed),
            "bundle_summary": _build_bundle_summary(results),
            "dimension_summary": _build_dimension_summary(results),
            "results": [_serialize_result(result) for result in results],
        }
        (output_dir / "report.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "report.md").write_text(_render_markdown(summary), encoding="utf-8")
        return summary


def _serialize_result(result: SampleResult) -> dict[str, Any]:
    return {
        "sample_id": result.sample_id,
        "bundle": result.bundle,
        "request_kind": result.request_kind,
        "response_kind": result.response_kind,
        "dimensions": result.dimensions,
        "passed": result.passed,
        "diffs": result.diffs,
        "candidate": {
            "status_code": result.candidate.status_code,
            "headers": result.candidate.headers,
            "json_body": result.candidate.json_body,
            "text_body": result.candidate.text_body,
            "binary_meta": result.candidate.binary_meta,
        },
        "baseline": None
        if result.baseline is None
        else {
            "status_code": result.baseline.status_code,
            "headers": result.baseline.headers,
            "json_body": result.baseline.json_body,
            "text_body": result.baseline.text_body,
            "binary_meta": result.baseline.binary_meta,
        },
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Contract Diff Report",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- mode: `{summary['mode']}`",
        f"- total: `{summary['total']}`",
        f"- passed: `{summary['passed']}`",
        f"- failed: `{summary['failed']}`",
        "",
        "## Bundle Summary",
        "",
        "| Bundle | Total | Passed | Failed |",
        "| --- | ---: | ---: | ---: |",
    ]
    for bundle, stats in summary["bundle_summary"].items():
        lines.append(f"| `{bundle}` | {stats['total']} | {stats['passed']} | {stats['failed']} |")
    lines.extend(
        [
            "",
            "## Dimension Summary",
            "",
            "| Dimension | Sample Count | Passed | Failed |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for dimension, stats in summary["dimension_summary"].items():
        lines.append(f"| `{dimension}` | {stats['total']} | {stats['passed']} | {stats['failed']} |")
    lines.extend(
        [
            "",
            "## Sample Results",
            "",
        ]
    )
    for result in summary["results"]:
        status_line = "PASS" if result["passed"] else "FAIL"
        lines.append(f"### `{result['sample_id']}` [{status_line}]")
        lines.append(f"- bundle: `{result['bundle']}`")
        lines.append(f"- request_kind: `{result['request_kind']}`")
        lines.append(f"- response_kind: `{result['response_kind']}`")
        lines.append(f"- dimensions: `{', '.join(result['dimensions'])}`")
        if result["diffs"]:
            for diff in result["diffs"]:
                lines.append(f"- diff: `{diff}`")
        else:
            lines.append("- diff: none")
        lines.append("")
    return "\n".join(lines)


def _resolve_dimensions(sample: ContractSample) -> list[str]:
    dimensions = ["status_code"]
    if sample.expected_headers:
        dimensions.append("headers")
    if sample.expected_json is not None or sample.response_kind == "json":
        dimensions.append("json")
    if sample.expected_text is not None or sample.response_kind == "text":
        dimensions.append("text/plain")
    if sample.request_multipart:
        dimensions.append("multipart")
    if sample.expected_binary is not None or sample.response_kind == "binary":
        dimensions.append("binary/download")
    if "set-cookie" in (sample.expected_headers or {}) or "cookie" in sample.request_headers:
        dimensions.append("cookie")
    return dimensions


def _build_bundle_summary(results: list[SampleResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for result in results:
        stats = summary[result.bundle]
        stats["total"] += 1
        stats["passed"] += int(result.passed)
        stats["failed"] += int(not result.passed)
    return dict(sorted(summary.items()))


def _build_dimension_summary(results: list[SampleResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for result in results:
        for dimension in result.dimensions:
            stats = summary[dimension]
            stats["total"] += 1
            stats["passed"] += int(result.passed)
            stats["failed"] += int(not result.passed)
    return dict(sorted(summary.items()))
