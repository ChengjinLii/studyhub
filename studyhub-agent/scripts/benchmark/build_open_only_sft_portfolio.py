#!/usr/bin/env python3
"""Assemble fail-closed internal and official external benchmark evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def evidence_ref(project: Path, path: Path) -> dict[str, str]:
    try:
        display = str(path.resolve().relative_to(project.resolve()))
    except ValueError:
        display = str(path.resolve())
    return {"path": display, "sha256": sha256(path)}


def development_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "episodes_scored": summary["episodes_scored"],
        "infra_excluded": summary["infra_excluded"],
        "strict_success_rate": summary["strict_success_rate"],
        "mean_diagnostic_score": summary["mean_score"],
        "mean_tool_calls": summary["tool_calls"]["mean"],
        "mean_latency_seconds": summary["latency_seconds"]["mean"],
        "run_id": summary["run_id"],
        "episodes_sha256": summary["episodes_sha256"],
    }


def variance_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    panel = summary["variance_panel"]
    return {
        "episodes_scored": summary["episodes_scored"],
        "infra_excluded": summary["infra_excluded"],
        "strict_success_rate": summary["strict_success_rate"],
        "pass_at_4": panel["pass_at_4"],
        "consistent_at_4": panel["consistent_at_4"],
        "mixed_outcome_rate": panel["mixed_outcome_rate"],
        "run_id": summary["run_id"],
        "episodes_sha256": summary["episodes_sha256"],
    }


def pending_result(reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_RUN",
        "reason": reason,
        "metrics": None,
        "evidence": None,
    }


def completed_result(metrics: dict[str, Any], evidence: dict[str, str]) -> dict[str, Any]:
    return {
        "status": "COMPLETED",
        "reason": None,
        "metrics": metrics,
        "evidence": evidence,
    }


def optional_summary(
    project: Path,
    path: Path | None,
    *,
    mode: str,
    pending_reason: str,
) -> dict[str, Any]:
    if path is None:
        return pending_result(pending_reason)
    summary = load_json(path)
    if summary.get("schema_version") != "studyhub.agentbench-run-summary.v2":
        raise RuntimeError(f"unexpected AgentBench summary schema: {path}")
    if summary.get("mode") != mode:
        raise RuntimeError(f"expected {mode} summary, got {summary.get('mode')}: {path}")
    if int(summary.get("infra_excluded", -1)) != 0:
        raise RuntimeError(f"portfolio refuses a summary with Infra exclusions: {path}")
    metrics = (
        development_metrics(summary) if mode == "development" else variance_metrics(summary)
    )
    return completed_result(metrics, evidence_ref(project, path))


def external_entry(
    name: str,
    lock_row: dict[str, Any],
    smoke_row: dict[str, Any],
) -> dict[str, Any]:
    setup = smoke_row["status"]
    model_status = (
        "LICENSE_REVIEW_REQUIRED"
        if setup == "LICENSE_REVIEW_REQUIRED"
        else "NOT_RUN"
    )
    entry = {
        "pinned_commit": lock_row["resolved_commit"],
        "setup_status": setup,
        "license": lock_row["license"],
        "official_metric_semantics_preserved": True,
        "official_invocation": smoke_row.get("official_invocation"),
        "model_results": {
            role: {
                "status": model_status,
                "raw_metric_name": None,
                "raw_metric_value": None,
            }
            for role in ("base", "mixed_v3_0", "open_only_v1_1")
        },
    }
    if name == "deepresearch_bench_ii":
        entry["official_metric_semantics_preserved"] = "NOT_APPLICABLE_LICENSE_BLOCKED"
    return entry


def build_portfolio(
    project: Path,
    *,
    candidate_development: Path | None = None,
    mixed_variance: Path | None = None,
    candidate_variance: Path | None = None,
    promotion_signals: Path | None = None,
) -> dict[str, Any]:
    benchmark_path = project / "benchmarks/studyhub-agent-v2/manifest.json"
    base_evidence_path = (
        project
        / "docs/benchmark/evidence/qwen35-9b-base-v2-development-variance-20260827.json"
    )
    mixed_evidence_path = (
        project / "docs/training/evidence/overnight-sft-teacher-20260828.json"
    )
    control_path = (
        project / "docs/training/evidence/open-only-sft-v1-1-control-diff.json"
    )
    promotion_policy_path = (
        project
        / "configs/program-v3/open-only-sft-v1.1-promotion-policy.json"
    )
    external_lock_path = project / "external_benchmarks/lock.json"
    external_smoke_path = project / "external_benchmarks/smoke-status.json"

    benchmark = load_json(benchmark_path)
    base = load_json(base_evidence_path)
    mixed = load_json(mixed_evidence_path)
    control = load_json(control_path)
    promotion_policy = load_json(promotion_policy_path)
    external_lock = load_json(external_lock_path)
    external_smoke = load_json(external_smoke_path)
    benchmark_hash = sha256(benchmark_path)
    expected_hashes = {
        base["benchmark_manifest_sha256"],
        mixed["lineage"]["benchmark_manifest_sha256"],
        control["model_affecting_controls"]["benchmark_manifest_sha256"][
            "open_only_v1_1"
        ],
    }
    if expected_hashes != {benchmark_hash}:
        raise RuntimeError(
            f"Benchmark hash drift in portfolio inputs: {sorted(expected_hashes)}"
        )
    if benchmark.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("AgentBench v2 is not frozen")
    if promotion_policy.get("benchmark_manifest_sha256") != benchmark_hash:
        raise RuntimeError("promotion policy does not lock the frozen Benchmark hash")
    if external_smoke.get("status") != "PASS":
        raise RuntimeError("external benchmark setup smoke is not PASS")

    base_development = {
        "status": "COMPLETED",
        "reason": None,
        "metrics": {
            "episodes_scored": base["development"]["episodes_scored"],
            "infra_excluded": base["development"]["infra_excluded"],
            "strict_success_rate": base["development"]["strict_success_rate"],
            "mean_diagnostic_score": base["development"][
                "mean_diagnostic_score"
            ],
            "mean_tool_calls": base["development"]["mean_tool_calls"],
            "mean_latency_seconds": base["development"]["mean_latency_seconds"],
            "run_id": base["development"]["run_id"],
            "episodes_sha256": base["development"]["artifact_hashes"][
                "episodes_jsonl"
            ],
        },
        "evidence": evidence_ref(project, base_evidence_path),
    }
    mixed_development = {
        "status": "COMPLETED",
        "reason": None,
        "metrics": {
            "episodes_scored": mixed["development_comparison"]["paired_tasks"],
            "infra_excluded": mixed["development_comparison"]["infra_excluded"],
            "strict_success_rate": mixed["development_comparison"]["sft"][
                "strict_success"
            ],
            "mean_diagnostic_score": mixed["development_comparison"]["sft"][
                "mean_diagnostic"
            ],
            "mean_tool_calls": mixed["development_comparison"]["sft"][
                "mean_tool_calls"
            ],
            "run_id": mixed["development_comparison"]["sft_run_id"],
            "episodes_sha256": mixed["development_comparison"][
                "sft_episodes_sha256"
            ],
        },
        "evidence": evidence_ref(project, mixed_evidence_path),
    }
    base_variance = {
        "status": "COMPLETED",
        "reason": None,
        "metrics": {
            "episodes_scored": base["variance"]["episodes_scored"],
            "infra_excluded": base["variance"]["infra_excluded"],
            "strict_success_rate": base["variance"]["strict_success_rate"],
            "pass_at_4": base["variance"]["pass_at_4"],
            "consistent_at_4": base["variance"]["consistent_at_4"],
            "mixed_outcome_rate": base["variance"]["mixed_outcome_rate"],
            "run_id": base["variance"]["run_id"],
            "episodes_sha256": base["variance"]["artifact_hashes"][
                "episodes_jsonl"
            ],
        },
        "evidence": evidence_ref(project, base_evidence_path),
    }

    external = {
        name: external_entry(
            name,
            row,
            external_smoke["benchmarks"][name],
        )
        for name, row in external_lock["benchmarks"].items()
    }
    if promotion_signals is None:
        signals = {
            name: {"status": "NOT_RUN", "evidence": None}
            for name in (
                "internal_paired_direction",
                "capability_tradeoffs",
                "cost_latency",
                "variance_direction",
                "external_direction",
            )
        }
    else:
        signals = load_json(promotion_signals)
        if signals.get("policy_sha256") != sha256(promotion_policy_path):
            raise RuntimeError("promotion signal policy hash mismatch")
        if signals.get("benchmark_manifest_sha256") != benchmark_hash:
            raise RuntimeError("promotion signal Benchmark hash mismatch")
        signals = signals["signals"]
    return {
        "schema_version": "studyhub.open-only-sft-benchmark-portfolio.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "READY_BUT_NOT_RUN",
        "candidate": "open-only-sft-v1.1",
        "benchmark": {
            "version": benchmark["benchmark_version"],
            "revision": benchmark["benchmark_revision"],
            "manifest_sha256": benchmark_hash,
            "development_mde_80_power_pp": 17.865,
            "sealed_used": False,
        },
        "training": {
            "base": {"status": "FROZEN_UNTRAINED_REFERENCE"},
            "mixed_v3_0": {"status": "COMPLETE_NEGATIVE_DIRECTIONAL_BASELINE"},
            "open_only_v1_1": {
                "status": "NOT_RUN",
                "reason": control["decision"],
            },
        },
        "internal": {
            "development": {
                "base": base_development,
                "mixed_v3_0": mixed_development,
                "open_only_v1_1": optional_summary(
                    project,
                    candidate_development,
                    mode="development",
                    pending_reason="FORMAL_TRAINING_NOT_RUN",
                ),
            },
            "variance": {
                "base": base_variance,
                "mixed_v3_0": optional_summary(
                    project,
                    mixed_variance,
                    mode="variance",
                    pending_reason="MIXED_VARIANCE_NOT_RUN",
                ),
                "open_only_v1_1": optional_summary(
                    project,
                    candidate_variance,
                    mode="variance",
                    pending_reason="CANDIDATE_VARIANCE_NOT_RUN",
                ),
            },
        },
        "external": external,
        "supported_suites": [
            "internal-development",
            "internal-variance",
            "bfcl",
            "tau2",
            "browsecomp-plus",
            "portfolio",
        ],
        "result_policy": {
            "aggregate_agent_score": "PROHIBITED",
            "official_external_metrics": "PRESERVE_UNMODIFIED",
            "external_not_run_blocks_promotion": True,
            "single_rollout_direction_is_not_promotion_evidence": True,
            "policy": evidence_ref(project, promotion_policy_path),
        },
        "promotion_signals": signals,
        "scope": {
            "rl_started": False,
            "sealed_used": False,
            "benchmark_modified": False,
        },
        "inputs": {
            "benchmark": evidence_ref(project, benchmark_path),
            "base": evidence_ref(project, base_evidence_path),
            "mixed": evidence_ref(project, mixed_evidence_path),
            "control": evidence_ref(project, control_path),
            "external_lock": evidence_ref(project, external_lock_path),
            "external_smoke": evidence_ref(project, external_smoke_path),
            "promotion_policy": evidence_ref(project, promotion_policy_path),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--candidate-development", type=Path)
    parser.add_argument("--mixed-variance", type=Path)
    parser.add_argument("--candidate-variance", type=Path)
    parser.add_argument("--promotion-signals", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_portfolio(
        args.project_root.resolve(),
        candidate_development=(
            args.candidate_development.resolve()
            if args.candidate_development
            else None
        ),
        mixed_variance=args.mixed_variance.resolve() if args.mixed_variance else None,
        candidate_variance=(
            args.candidate_variance.resolve() if args.candidate_variance else None
        ),
        promotion_signals=(
            args.promotion_signals.resolve() if args.promotion_signals else None
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps({"status": payload["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
