"""Gate the Router for an isolated offline RL pilot."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "studyhub.agent.router.rl_readiness.v1"


def assess_rl_readiness(
    *,
    production_gate: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    decoding = run_manifest.get("decoding")
    decoding = decoding if isinstance(decoding, Mapping) else {}
    variants = production_gate.get("variants")
    variants = variants if isinstance(variants, Mapping) else {}
    required_variants = production_gate.get("required_variants")
    required_variants = (
        set(required_variants) if isinstance(required_variants, list) else set()
    )
    checks = {
        "development_gate_passed": production_gate.get("passed") is True,
        "raw_and_normalized_passed": required_variants == {"raw", "normalized"}
        and all(
            isinstance(variants.get(name), Mapping)
            and variants[name].get("passed") is True
            for name in ("raw", "normalized")
        ),
        "typed_constrained_projection_enabled": decoding.get(
            "typed_constrained_projection"
        )
        is True,
        "deterministic_argument_protection_enabled": decoding.get(
            "deterministic_argument_protection"
        )
        is True,
        "adapter_pinned": bool(run_manifest.get("adapter_sha256")),
        "development_dataset_pinned": bool(run_manifest.get("dataset_sha256")),
        "production_api_not_called": run_manifest.get("production_api_called") is False,
        "production_database_not_accessed": run_manifest.get(
            "production_database_accessed"
        )
        is False,
        "final_holdout_unread": production_gate.get("final_holdout_read") is False
        and run_manifest.get("final_holdout_read") is False,
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready_for_offline_rl_pilot": not blockers,
        "ready_for_production_rollout": False,
        "production_rollout_reason": (
            "Offline RL policy, independent evaluation and final holdout remain pending."
        ),
        "checks": checks,
        "blockers": blockers,
        "reward_boundary": {
            "runtime_owned_not_rewarded": [
                "strict_json_and_contract",
                "tool_allowlist_and_permission_boundary",
                "tool_budget_and_force_final",
                "trusted_material_ids",
                "explicit_page_numbers",
                "bounded_argument_ranges",
            ],
            "policy_owned_reward_candidates": [
                "semantic_tool_selection",
                "query_rewrite_quality",
                "evidence_acquisition_order",
                "stop_or_continue_decision",
                "answer_grounding_and_utility",
            ],
        },
        "data_policy": {
            "development_diagnostic_training_export_allowed": False,
            "final_holdout_read": False,
            "production_data_accessed": False,
        },
    }


def gate_rl_readiness_root(
    *,
    root: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    gate_path = root / "gate.json"
    manifest_path = root / "run_manifest.json"
    if not gate_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("gate.json and run_manifest.json are required")
    result = assess_rl_readiness(
        production_gate=json.loads(gate_path.read_text(encoding="utf-8")),
        run_manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
    )
    destination = output_path or root / "rl_readiness.json"
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-not-ready", action="store_true")
    args = parser.parse_args()
    result = gate_rl_readiness_root(root=args.root, output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_not_ready and not result["ready_for_offline_rl_pilot"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
