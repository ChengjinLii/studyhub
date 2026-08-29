from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.train.collect_lr_audit_segments import collect


def _attempt(
    log_root: Path,
    evidence_root: Path,
    *,
    prefix: str,
    suffix: str,
    start: int,
    observed: int,
) -> None:
    attempt_id = f"{prefix}-attempt-{suffix}"
    (log_root / f"{attempt_id}.run.json").write_text(
        json.dumps(
            {
                "config": {
                    "overrides": [f"studyhub_attempt_start_step={start}"]
                }
            }
        ),
        encoding="utf-8",
    )
    metrics = evidence_root / attempt_id / "metrics" / "trainer.json"
    metrics.parent.mkdir(parents=True)
    metrics.write_text(
        json.dumps({"series": {"sft/lr": [0.0] * observed}}),
        encoding="utf-8",
    )


def test_collect_segments_trims_rolled_back_tail(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    evidence = tmp_path / "evidence"
    logs.mkdir()
    prefix = "controlled-trial"
    _attempt(
        logs,
        evidence,
        prefix=prefix,
        suffix="001",
        start=0,
        observed=8,
    )
    _attempt(
        logs,
        evidence,
        prefix=prefix,
        suffix="002",
        start=6,
        observed=4,
    )

    segments = collect(
        logs,
        evidence,
        attempt_prefix=prefix,
        expected_updates=10,
    )

    assert [(start, count) for _, start, count in segments] == [(0, 6), (6, 4)]


def test_collect_segments_fails_when_durable_metrics_are_missing(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    evidence = tmp_path / "evidence"
    logs.mkdir()
    _attempt(
        logs,
        evidence,
        prefix="trial",
        suffix="001",
        start=0,
        observed=2,
    )

    with pytest.raises(RuntimeError, match="2 LR points but 4 are required"):
        collect(logs, evidence, attempt_prefix="trial", expected_updates=4)


def test_collect_segments_ignores_incomplete_attempts_at_same_recovery_step(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    evidence = tmp_path / "evidence"
    logs.mkdir()
    prefix = "resumed-trial"
    _attempt(logs, evidence, prefix=prefix, suffix="001", start=0, observed=8)
    _attempt(logs, evidence, prefix=prefix, suffix="002", start=6, observed=0)
    _attempt(logs, evidence, prefix=prefix, suffix="003", start=6, observed=2)
    _attempt(logs, evidence, prefix=prefix, suffix="004", start=6, observed=4)

    segments = collect(
        logs,
        evidence,
        attempt_prefix=prefix,
        expected_updates=10,
    )

    assert [(path.parts[-3], start, count) for path, start, count in segments] == [
        (f"{prefix}-attempt-001", 0, 6),
        (f"{prefix}-attempt-004", 6, 4),
    ]


def test_collect_segments_fails_closed_for_multiple_complete_attempts(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    evidence = tmp_path / "evidence"
    logs.mkdir()
    prefix = "ambiguous-trial"
    _attempt(logs, evidence, prefix=prefix, suffix="001", start=0, observed=4)
    _attempt(logs, evidence, prefix=prefix, suffix="002", start=0, observed=4)

    with pytest.raises(RuntimeError, match="ambiguous durable attempts at step 0"):
        collect(logs, evidence, attempt_prefix=prefix, expected_updates=4)
