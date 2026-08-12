"""Persist a Train/Validation-only audit of the constrained Router action space."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..reward import score_double_ledger
from ..spec import sha256_file
from .actions import build_action_space
from .spec import load_maturity_states


def audit_action_space(
    *,
    train_path: Path,
    validation_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite action audit: {output_path}")
    states = [
        *load_maturity_states(train_path, splits={"train"}),
        *load_maturity_states(validation_path, splits={"validation"}),
    ]
    size_distribution: Counter[int] = Counter()
    route_distribution: Counter[str] = Counter()
    errors: list[str] = []
    candidates = 0
    oracle_gaps: list[float] = []
    for state in states:
        space = build_action_space(state)
        size_distribution[len(space.candidates)] += 1
        if len(space.codes) != len(set(space.codes)):
            errors.append(f"duplicate_code:{state.state_id}")
        if space.oracle_route not in space.routes:
            errors.append(f"oracle_unavailable:{state.state_id}")
        for candidate in space.candidates:
            candidates += 1
            route_distribution[candidate.route] += 1
            ledger = score_double_ledger(candidate.output, state)
            failed = [name for name, passed in ledger.raw.hard_gates.items() if not passed]
            if failed:
                errors.append(
                    f"raw_hard_gate:{state.state_id}:{candidate.route}:{','.join(failed)}"
                )
            if candidate.route == space.oracle_route:
                oracle_gaps.append(abs(ledger.constraint_dependency_delta))
                components = ledger.raw.components
                if components["tool_choice"] != 1.0 or components["stop_decision"] != 1.0:
                    errors.append(f"oracle_choice_mismatch:{state.state_id}")
    checks = {
        "states_present": len(states) > 0,
        "all_raw_candidates_pass_hard_gates": not any(
            value.startswith("raw_hard_gate:") for value in errors
        ),
        "oracle_always_available": not any(
            value.startswith("oracle_unavailable:") for value in errors
        ),
        "codes_unique_per_state": not any(
            value.startswith("duplicate_code:") for value in errors
        ),
        "oracle_choice_matches_rubric": not any(
            value.startswith("oracle_choice_mismatch:") for value in errors
        ),
        "oracle_raw_executable_gap_zero": bool(oracle_gaps) and max(oracle_gaps) == 0.0,
    }
    result = {
        "schema_version": "studyhub.agent.router_rl.action_space_audit.v2",
        "passed": all(checks.values()) and not errors,
        "checks": checks,
        "errors": errors,
        "states": len(states),
        "candidate_actions": candidates,
        "oracle_actions": len(oracle_gaps),
        "action_space_size_distribution": {
            str(size): count for size, count in sorted(size_distribution.items())
        },
        "route_distribution": dict(sorted(route_distribution.items())),
        "oracle_constraint_dependency_absolute_maximum": max(oracle_gaps),
        "train_sha256": sha256_file(train_path),
        "validation_sha256": sha256_file(validation_path),
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_action_space(
        train_path=args.train.resolve(),
        validation_path=args.validation.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
