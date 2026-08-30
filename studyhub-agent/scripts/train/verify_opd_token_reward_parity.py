#!/usr/bin/env python3
"""Verify the frozen THUNLP OPD mathematical contract and upstream locks."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.opd.token_reward_parity import run_synthetic_parity_gate  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkout_audit(checkout: Path, expected: dict[str, Any]) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    sources = {
        relative: {
            "expected_sha256": expected_hash,
            "actual_sha256": _sha256(checkout / relative),
        }
        for relative, expected_hash in expected["critical_sources"].items()
    }
    return {
        "commit": commit,
        "expected_commit": expected["commit"],
        "commit_matches": commit == expected["commit"],
        "critical_sources": sources,
        "critical_sources_match": all(
            item["actual_sha256"] == item["expected_sha256"] for item in sources.values()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thunlp-checkout", type=Path)
    parser.add_argument("--verl-checkout", type=Path)
    args = parser.parse_args()

    lock_path = PROJECT_ROOT / "training/opd/upstream.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    parity = run_synthetic_parity_gate()
    upstream: dict[str, Any] = {}
    if args.thunlp_checkout:
        upstream["thunlp_opd"] = _checkout_audit(args.thunlp_checkout, lock["thunlp_opd"])
    if args.verl_checkout:
        upstream["official_verl"] = _checkout_audit(args.verl_checkout, lock["official_verl"])

    upstream_pass = all(
        audit["commit_matches"] and audit["critical_sources_match"] for audit in upstream.values()
    )
    status = (
        "PASS_THUNLP_TOKEN_REWARD_DIRECT_MATH"
        if parity["status"] == "PASS_THUNLP_TOKEN_REWARD_DIRECT_MATH" and upstream_pass
        else "FAIL"
    )
    report = {
        **parity,
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "upstream_lock_sha256": _sha256(lock_path),
        "upstream_checkouts": upstream,
        "runtime_backend_parity": "NOT_RUN",
        "opd_training_authorized_by_this_gate": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS_THUNLP_TOKEN_REWARD_DIRECT_MATH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
