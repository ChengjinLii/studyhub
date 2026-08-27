#!/usr/bin/env python3
"""Write a fail-closed marker for the one authorized bounded overnight SFT."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.train.record_formal_sft_completion import build_marker, load_json, sha256


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    authorization = load_json(args.authorization)
    budget = authorization.get("budget", {})
    if authorization.get("status") != "AUTHORIZED_PENDING_RUN":
        raise RuntimeError("overnight authorization is not pending")
    if args.expected_updates != budget.get("planned_optimizer_updates"):
        raise RuntimeError("completion update count differs from authorization")
    marker = build_marker(args)
    metadata = load_json(args.run_metadata)
    captured = metadata.get("run_authorization", {})
    if captured.get("sha256") != sha256(args.authorization):
        raise RuntimeError("run metadata is not bound to this authorization")
    marker.update(
        {
            "schema_version": "studyhub.overnight-sft-completion.v1",
            "authorization_id": authorization["authorization_id"],
            "authorization_sha256": sha256(args.authorization),
            "maximum_wall_time_seconds": budget["maximum_wall_time_seconds"],
            "no_rl": authorization["scope"]["no_rl"],
            "sealed_used": False,
            "quality_claim": "PENDING_INDEPENDENT_DEVELOPMENT_EVALUATION",
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(marker, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
