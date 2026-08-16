"""Diagnose raw/executable Router reward gaps without generating new outputs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .reward import score_double_ledger
from .spec import canonical_json, load_states, sha256_file


def diagnose(*, states_path: Path, predictions: dict[str, Path]) -> dict[str, Any]:
    states = {state.state_id: state for state in load_states(states_path)}
    policies: dict[str, Any] = {}
    for label, prediction_path in predictions.items():
        rows = [json.loads(line) for line in prediction_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        gaps: list[float] = []
        corrections: Counter[str] = Counter()
        families: dict[str, list[float]] = defaultdict(list)
        state_rows: list[dict[str, Any]] = []
        for row in rows:
            state_id = str(row["state_id"])
            if state_id not in states:
                raise ValueError(f"prediction references unknown state: {state_id}")
            ledger = score_double_ledger(str(row["raw_generated"]), states[state_id])
            gap = ledger.constraint_dependency_delta
            gaps.append(gap)
            corrections.update(ledger.constraint_corrections)
            families[states[state_id].family].append(gap)
            if gap:
                state_rows.append(
                    {
                        "state_id": state_id,
                        "family": states[state_id].family,
                        "raw_reward": ledger.raw.policy_reward,
                        "executable_reward": ledger.executable.policy_reward,
                        "gap": gap,
                        "corrections": list(ledger.constraint_corrections),
                        "raw_choice_success": _choice_success(ledger.raw.components),
                        "executable_choice_success": _choice_success(ledger.executable.components),
                    }
                )
        policies[label] = {
            "predictions_path": str(prediction_path.resolve()),
            "predictions_sha256": sha256_file(prediction_path),
            "states": len(rows),
            "mean_signed_reward_gap": _mean(gaps),
            "mean_absolute_reward_gap": _mean([abs(value) for value in gaps]),
            "negative_gap_states": sum(value < 0 for value in gaps),
            "positive_gap_states": sum(value > 0 for value in gaps),
            "zero_gap_states": sum(value == 0 for value in gaps),
            "corrections": dict(sorted(corrections.items())),
            "family_mean_signed_gap": {
                family: _mean(values) for family, values in sorted(families.items())
            },
            "nonzero_state_rows": state_rows,
        }
    labels = list(predictions)
    comparison: dict[str, Any] = {}
    if len(labels) == 2:
        baseline, candidate = labels
        comparison = {
            "baseline": baseline,
            "candidate": candidate,
            "candidate_minus_baseline_signed_gap": round(
                policies[candidate]["mean_signed_reward_gap"]
                - policies[baseline]["mean_signed_reward_gap"],
                6,
            ),
            "candidate_minus_baseline_absolute_gap": round(
                policies[candidate]["mean_absolute_reward_gap"]
                - policies[baseline]["mean_absolute_reward_gap"],
                6,
            ),
        }
    return {
        "schema_version": "studyhub.agent.router_rl.constraint_gap_diagnostic.v2",
        "method": "offline_rescore_frozen_predictions_after_constraint_projector_fix",
        "states_path": str(states_path.resolve()),
        "states_sha256": sha256_file(states_path),
        "legacy_test_consumed": True,
        "allowed_for_v2_training_selection_or_gate": False,
        "production_accessed": False,
        "policies": policies,
        "comparison": comparison,
    }


def _choice_success(components: dict[str, float | None]) -> bool:
    return components.get("tool_choice") == 1.0 and components.get("stop_decision") == 1.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(
        states_path=args.states.resolve(),
        predictions={"baseline_sft": args.baseline.resolve(), "seed_3407": args.candidate.resolve()},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(canonical_json({"output": str(args.output.resolve()), "comparison": result["comparison"]}))


if __name__ == "__main__":
    main()
