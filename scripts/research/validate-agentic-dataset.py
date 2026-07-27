#!/usr/bin/env python3
"""Validate immutable Agent pilot trajectories before any dataset export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
for import_root in (ROOT_DIR / "backend", ROOT_DIR):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)

from app.agentic_platform.domain.data_policy import ExportTarget  # noqa: E402
from app.agentic_platform.domain.hashing import canonical_json  # noqa: E402
from ml.agentic_platform.collection.pilot import (  # noqa: E402
    PilotConfigurationError,
    load_pilot_manifest,
    load_pilot_report,
)
from ml.agentic_platform.collection.validation import (  # noqa: E402
    PilotGateAuthorizationError,
    authorize_training_collection,
    validate_pilot_dataset,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify pilot manifests, token provenance, data policy, and Go Gate metrics."
    )
    parser.add_argument("--pilot-report", required=True, help="pilot-run.json created by run-agentic-pilot.py")
    parser.add_argument("--scenario-manifest", help="Optional manifest to validate child-transition expectations")
    parser.add_argument("--target", choices=[target.value for target in ExportTarget], default=ExportTarget.TRAIN.value)
    parser.add_argument("--required-count", type=int, default=100)
    parser.add_argument("--long-queue-threshold-ms", type=float, default=60_000.0)
    parser.add_argument("--ci-passed", action="store_true", help="Assert that the required CI suite is green")
    parser.add_argument(
        "--mysql-migration-verified",
        action="store_true",
        help="Assert that the additive MySQL migration was verified in the target environment",
    )
    parser.add_argument("--output", required=True, help="Path for the JSON gate report")
    parser.add_argument(
        "--authorize-collection",
        action="store_true",
        help="After a passing 100-run Train Gate, write collection-authorization.json next to --output",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = load_pilot_report(args.pilot_report)
        manifest = load_pilot_manifest(args.scenario_manifest) if args.scenario_manifest else None
        gate = validate_pilot_dataset(
            report,
            target=ExportTarget(args.target),
            scenario_manifest=manifest,
            required_count=args.required_count,
            long_queue_threshold_ms=args.long_queue_threshold_ms,
            ci_passed=args.ci_passed,
            mysql_migration_verified=args.mysql_migration_verified,
        )
    except (PilotConfigurationError, ValueError) as exc:
        print(f"agentic-dataset: {exc}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(canonical_json(gate, exclude_fields=()) + "\n", encoding="utf-8")
    temporary.replace(output)
    if args.authorize_collection:
        try:
            authorization = authorize_training_collection(gate)
        except PilotGateAuthorizationError as exc:
            print(f"agentic-dataset: {exc}", file=sys.stderr)
            return 1
        authorization_output = output.with_name("collection-authorization.json")
        authorization_temporary = authorization_output.with_name(f".{authorization_output.name}.tmp")
        authorization_temporary.write_text(canonical_json(authorization, exclude_fields=()) + "\n", encoding="utf-8")
        authorization_temporary.replace(authorization_output)
    print(json.dumps(gate.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
    return 0 if gate.gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
