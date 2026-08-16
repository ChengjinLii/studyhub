from __future__ import annotations

from app.ops.schema_baseline import audit_fingerprint, check_baseline


def _audit() -> dict[str, object]:
    return {
        "missingTables": ["optional_table"],
        "missingColumns": [
            {"table": "users", "column": "session_version", "expectedType": "INTEGER", "nullable": False, "default": 0}
        ],
        "columnWarnings": [],
        "missingIndexes": [],
    }


def test_schema_baseline_accepts_exact_reviewed_drift() -> None:
    fingerprint, counts = audit_fingerprint(_audit())
    result = check_baseline(_audit(), {"fingerprint": fingerprint, "counts": counts})
    assert result["matchesReviewedBaseline"] is True


def test_schema_baseline_rejects_new_drift_even_when_counts_match() -> None:
    fingerprint, counts = audit_fingerprint(_audit())
    changed = _audit()
    changed["missingTables"] = ["different_table"]
    result = check_baseline(changed, {"fingerprint": fingerprint, "counts": counts})
    assert result["matchesReviewedBaseline"] is False
