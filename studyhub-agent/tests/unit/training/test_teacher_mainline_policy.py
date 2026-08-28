from __future__ import annotations

from pathlib import Path

from scripts.data.validate_teacher_mainline_policy import validate

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_legacy_teacher_reverse_replay_is_frozen_out_of_mainline() -> None:
    audit = validate(PROJECT_ROOT)

    assert audit["status"] == "PASS"
    assert audit["decision"] == "LEGACY_REVERSE_REPLAY_FROZEN_NOT_MAINLINE"
    assert audit["observed"]["teacher_sources_in_active_dataset"] == []
    assert audit["observed"]["teacher_candidate_rows"] == 1
    assert audit["scope"]["teacher_collection_started"] is False
