from __future__ import annotations

import json
from pathlib import Path

from scripts.train.audit_sft_lr_schedule import audit, expected_cosine_lr


def _metrics(path: Path, values: list[float]) -> Path:
    path.write_text(
        json.dumps({"series": {"sft/lr": values}}),
        encoding="utf-8",
    )
    return path


def test_lr_schedule_audit_accepts_contiguous_recovered_segments(tmp_path: Path) -> None:
    expected = [
        expected_cosine_lr(
            step,
            base_lr=2e-5,
            total_steps=100,
            warmup_fraction=0.1,
        )
        for step in range(8)
    ]
    first = _metrics(tmp_path / "first.json", expected[:5])
    second = _metrics(tmp_path / "second.json", expected[5:])

    result = audit(
        [(first, 0, 5), (second, 5, 3)],
        base_lr=2e-5,
        total_steps=100,
        warmup_fraction=0.1,
        expected_updates=8,
    )

    assert result["status"] == "PASS"
    assert result["mismatch_count"] == 0
    assert result["coverage"]["last_global_step"] == 7


def test_lr_schedule_audit_rejects_scheduler_restart(tmp_path: Path) -> None:
    first = _metrics(
        tmp_path / "first.json",
        [
            expected_cosine_lr(
                step,
                base_lr=2e-5,
                total_steps=100,
                warmup_fraction=0.1,
            )
            for step in range(5)
        ],
    )
    restarted = _metrics(
        tmp_path / "restarted.json",
        [
            expected_cosine_lr(
                step,
                base_lr=2e-5,
                total_steps=100,
                warmup_fraction=0.1,
            )
            for step in range(3)
        ],
    )

    result = audit(
        [(first, 0, 5), (restarted, 5, 3)],
        base_lr=2e-5,
        total_steps=100,
        warmup_fraction=0.1,
        expected_updates=8,
    )

    assert result["status"] == "FAIL"
    assert result["mismatch_count"] == 3
    assert "lr_schedule_mismatches:3" in result["failures"]


def test_lr_schedule_audit_accepts_a_later_attempt_segment(tmp_path: Path) -> None:
    values = [
        expected_cosine_lr(
            step,
            base_lr=2e-5,
            total_steps=100,
            warmup_fraction=0.1,
        )
        for step in range(5, 8)
    ]
    segment = _metrics(tmp_path / "resumed.json", values)

    result = audit(
        [(segment, 5, 3)],
        base_lr=2e-5,
        total_steps=100,
        warmup_fraction=0.1,
        expected_updates=3,
        expected_start_step=5,
    )

    assert result["status"] == "PASS"
    assert result["coverage"]["first_global_step"] == 5
