#!/usr/bin/env python3
"""Apply the frozen fail-closed promotion policy to Open-Only v1.1 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def completed(portfolio: dict[str, Any], section: str, role: str) -> bool:
    return portfolio.get("internal", {}).get(section, {}).get(role, {}).get("status") == "COMPLETED"


def external_complete(portfolio: dict[str, Any], benchmark: str) -> bool:
    results = portfolio.get("external", {}).get(benchmark, {}).get("model_results", {})
    return all(results.get(role, {}).get("status") == "COMPLETED" for role in ("base", "mixed_v3_0", "open_only_v1_1"))


def decide(control: dict[str, Any], portfolio: dict[str, Any]) -> dict[str, Any]:
    hard_controls_pass = not control.get("hard_control_failures") and not control.get("provenance_failures")
    recovery = control.get("runtime_correction_diff", {}).get("recovery_contract", {})
    recovery_pass = (
        recovery.get("eligible") is True
        and control.get("runtime_correction_diff", {}).get("status") == "SEMANTIC_EQUIVALENCE_CONFIRMED_BY_R1_R4"
    )
    sealed_unused = (
        portfolio.get("scope", {}).get("sealed_used") is False and control.get("scope", {}).get("sealed_used") is False
    )
    candidate_training_complete = portfolio.get("training", {}).get("open_only_v1_1", {}).get("status") == "COMPLETE"
    development_complete = all(
        completed(portfolio, "development", role) for role in ("base", "mixed_v3_0", "open_only_v1_1")
    )
    variance_complete = all(completed(portfolio, "variance", role) for role in ("base", "mixed_v3_0", "open_only_v1_1"))
    external_required_complete = all(external_complete(portfolio, benchmark) for benchmark in ("bfcl", "tau2"))
    signals = portfolio.get("promotion_signals", {})
    internal_direction_pass = all(
        signals.get(name, {}).get("status") == "PASS"
        for name in (
            "internal_paired_direction",
            "capability_tradeoffs",
            "cost_latency",
        )
    )
    variance_direction_pass = signals.get("variance_direction", {}).get("status") == "PASS"
    external_direction_pass = signals.get("external_direction", {}).get("status") == "PASS"

    if not sealed_unused or not hard_controls_pass:
        decision = "BLOCKED_CONTROL_DRIFT"
    elif not recovery_pass:
        decision = "BLOCKED_RECOVERY_CONTRACT"
    elif not candidate_training_complete or not development_complete:
        decision = "TRAINING_CONTRACT_PASS_EVAL_PENDING"
    elif not internal_direction_pass:
        decision = "INTERNAL_DIRECTIONAL_EVIDENCE_ONLY"
    elif not variance_complete:
        decision = "BLOCKED_PENDING_VARIANCE"
    elif not variance_direction_pass:
        decision = "INTERNAL_DIRECTIONAL_EVIDENCE_ONLY"
    elif not external_required_complete:
        decision = "BLOCKED_PENDING_EXTERNAL_EVIDENCE"
    elif not external_direction_pass:
        decision = "INTERNAL_DIRECTIONAL_EVIDENCE_ONLY"
    else:
        decision = "CANDIDATE_READY_FOR_FINAL_FREEZE"

    requirements = {
        "training_control": {
            "status": "PASS" if hard_controls_pass else "FAIL",
            "required": True,
        },
        "recovery_contract": {
            "status": "PASS" if recovery_pass else "NOT_PASS",
            "required": True,
            "r4": recovery.get("r4_status"),
        },
        "candidate_training": {
            "status": "PASS" if candidate_training_complete else "NOT_RUN",
            "required": True,
        },
        "internal_development": {
            "status": "PASS" if development_complete else "INCOMPLETE",
            "required": True,
        },
        "internal_direction_and_tradeoffs": {
            "status": "PASS" if internal_direction_pass else "NOT_PASS",
            "required": True,
        },
        "internal_variance": {
            "status": "PASS" if variance_complete else "INCOMPLETE",
            "required": True,
        },
        "variance_direction": {
            "status": "PASS" if variance_direction_pass else "NOT_PASS",
            "required": True,
        },
        "external_bfcl_tau2": {
            "status": "PASS" if external_required_complete else "NOT_RUN",
            "required": True,
        },
        "external_direction": {
            "status": "PASS" if external_direction_pass else "NOT_PASS",
            "required": True,
        },
        "sealed_unused": {
            "status": "PASS" if sealed_unused else "FAIL",
            "required": True,
        },
    }
    return {
        "decision": decision,
        "requirements": requirements,
        "claim_boundary": (
            "No overall Agentic improvement or final confirmation claim is permitted "
            "until controlled training, paired Development, variance, and official "
            "BFCL/tau2 evidence all pass. Sealed remains unused."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--control",
        type=Path,
        default=(PROJECT_ROOT / "docs/training/evidence/open-only-sft-v1-1-control-diff.json"),
    )
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=(PROJECT_ROOT / "docs/training/evidence/open-only-sft-v1-1-benchmark-portfolio.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    control = load_json(args.control)
    portfolio = load_json(args.portfolio)
    result = decide(control, portfolio)
    payload = {
        "schema_version": "studyhub.open-only-sft-promotion-decision.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "candidate": "open-only-sft-v1.1",
        **result,
        "evidence": {
            "control": {"path": str(args.control), "sha256": sha256(args.control)},
            "portfolio": {
                "path": str(args.portfolio),
                "sha256": sha256(args.portfolio),
            },
        },
        "scope": {
            "rl_started": False,
            "sealed_used": False,
            "benchmark_modified": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps({"decision": payload["decision"], "output": str(args.output)}))
    return 0 if payload["decision"] == "CANDIDATE_READY_FOR_FINAL_FREEZE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
