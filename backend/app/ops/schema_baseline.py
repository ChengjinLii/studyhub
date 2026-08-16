from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.ops.schema_audit import build_schema_audit_payload


def audit_fingerprint(payload: dict[str, Any]) -> tuple[str, dict[str, int]]:
    canonical = {
        "missingTables": sorted(payload.get("missingTables") or []),
        "missingColumns": sorted(
            (
                item["table"],
                item["column"],
                item["expectedType"],
                item["nullable"],
                str(item.get("default")),
            )
            for item in payload.get("missingColumns") or []
        ),
        "columnWarnings": sorted(
            (
                item["table"],
                item["column"],
                item["kind"],
                str(item.get("expectedType")),
                str(item.get("actualType")),
                str(item.get("expectedNullable")),
                str(item.get("actualNullable")),
                str(item.get("expectedDefault")),
                str(item.get("actualDefault")),
            )
            for item in payload.get("columnWarnings") or []
        ),
        "missingIndexes": sorted(
            (item["table"], item["index"], tuple(item["columns"]))
            for item in payload.get("missingIndexes") or []
        ),
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    counts = {key: len(value) for key, value in canonical.items()}
    return hashlib.sha256(encoded).hexdigest(), counts


def check_baseline(payload: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    fingerprint, counts = audit_fingerprint(payload)
    expected_fingerprint = str(baseline.get("fingerprint") or "")
    expected_counts = baseline.get("counts") or {}
    matches = fingerprint == expected_fingerprint and counts == expected_counts
    return {
        "matchesReviewedBaseline": matches,
        "fingerprint": fingerprint,
        "expectedFingerprint": expected_fingerprint,
        "counts": counts,
        "expectedCounts": expected_counts,
        "reviewedAt": baseline.get("reviewedAt"),
        "note": baseline.get("note"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check complete production schema drift against reviewed baseline")
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    result = check_baseline(build_schema_audit_payload(), baseline)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["matchesReviewedBaseline"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
