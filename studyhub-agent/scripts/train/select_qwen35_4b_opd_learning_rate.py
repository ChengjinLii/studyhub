#!/usr/bin/env python3
"""Choose 1e-6 or 3e-6 from two same-prompt strict OPD micro-pilots."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from scripts.train.record_formal_sft_completion import sha256


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lr1e6", type=Path, required=True)
    parser.add_argument("--lr3e6", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    low = load_json(args.lr1e6)
    high = load_json(args.lr3e6)
    expected = [(low, 1.0e-6), (high, 3.0e-6)]
    failures = []
    passes = {}
    for row, learning_rate in expected:
        status_ok = row.get("status") == "PASS_OPD_LR_MICRO_PILOT"
        identity_ok = float(row.get("learning_rate", -1)) == learning_rate
        updates_ok = int(row.get("optimizer_updates", -1)) == 16
        passes[learning_rate] = status_ok and identity_ok and updates_ok
        if not passes[learning_rate]:
            failures.append(f"lr_{learning_rate:g}_pilot_failed")
        if not identity_ok:
            failures.append(f"lr_{learning_rate:g}_identity_drift")
        if not updates_ok:
            failures.append(f"lr_{learning_rate:g}_update_count_drift")
    low_metrics = low.get("metrics", {})
    high_metrics = high.get("metrics", {})
    if passes.get(3.0e-6) and passes.get(1.0e-6):
        low_length = low_metrics.get("sequence_length_mean")
        high_length = high_metrics.get("sequence_length_mean")
        high_stable = (
            float(high_metrics["grad_norm_max"])
            <= max(float(low_metrics["grad_norm_max"]) * 3.0, 1.0)
            and float(high_metrics["tool_validity_mean"])
            >= float(low_metrics["tool_validity_mean"]) - 0.03
            and (
                low_length is None
                or high_length is None
                or float(high_length) <= float(low_length) * 1.5
            )
        )
        selected = 3.0e-6 if high_stable else 1.0e-6
    elif passes.get(3.0e-6):
        # The surviving pilot is usable, but no cross-LR stability claim is possible.
        high_stable = None
        selected = 3.0e-6
    elif passes.get(1.0e-6):
        high_stable = False
        selected = 1.0e-6
    else:
        high_stable = False
        selected = None
    result = {
        "schema_version": "studyhub.qwen35-4b-opd-lr-selection.v1",
        "status": (
            "PASS_OPD_LR_SELECTION" if selected is not None else "OPD_PILOT_FAILED"
        ),
        "selected_learning_rate": selected,
        "selection_rule": (
            "prefer_3e-6_when_both_pass_and_no_grad_tool_or_length_instability; otherwise_select_the_only_passing_pilot"
        ),
        "same_prompt_seed_contract": True,
        "high_lr_stable": high_stable,
        "failures": failures,
        "pilots": {
            "1e-6": low,
            "3e-6": high,
        },
        "lineage": {
            "lr1e6_sha256": sha256(args.lr1e6),
            "lr3e6_sha256": sha256(args.lr3e6),
        },
        "sealed_used": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if selected is not None else 3


if __name__ == "__main__":
    raise SystemExit(main())
