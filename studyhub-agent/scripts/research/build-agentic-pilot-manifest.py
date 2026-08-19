#!/usr/bin/env python3
"""Generate the deterministic 100-scenario offline Pilot manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ROOT_DIR.parent
for import_root in (WORKSPACE_ROOT / "backend", ROOT_DIR):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)

from app.agentic_platform.domain.hashing import canonical_json  # noqa: E402
from ml.agentic_platform.collection.offline_guard import default_artifact_root  # noqa: E402
from ml.agentic_platform.collection.snapshot_pilot_data import build_pilot_manifest  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the isolated StudyHub 100-scenario Snapshot Pilot manifest.")
    parser.add_argument("--run-name", required=True, help="Path-safe run name below the ignored offline artifact root")
    parser.add_argument("--artifact-root", default=str(default_artifact_root()))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_name = args.run_name.strip()
    if not run_name or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for character in run_name):
        raise SystemExit("run-name must contain only letters, digits, dot, dash, or underscore")
    artifact_root = Path(args.artifact_root).expanduser().resolve()
    run_root = (artifact_root / run_name).resolve()
    if not run_root.is_relative_to(artifact_root):
        raise SystemExit("run-name escapes the offline artifact root")
    run_root.mkdir(parents=True, exist_ok=True)
    manifest = build_pilot_manifest(trajectory_root=run_root / "trajectories")
    output = run_root / "scenario-manifest.json"
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(canonical_json(manifest, exclude_fields=()) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
