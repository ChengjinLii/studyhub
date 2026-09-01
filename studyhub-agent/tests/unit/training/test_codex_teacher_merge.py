import json
from pathlib import Path

import pytest

from scripts.data.merge_codex_hermes_teacher_datasets import (
    merge_batches,
    sha256,
    stable_row_sha256,
)
from studyhub_agent.trajectory.runtime_sft import trajectory_fingerprint


def _row(run_id: str, user_content: str) -> dict:
    row = {
        "source_dataset": "codex_hermes_teacher_v1",
        "source_id": run_id,
        "source_group_ids": [f"group-{run_id}"],
        "task_family": "rag_query_rewrite_citation",
        "quality_tier": "teacher_verified_complete",
        "teacher": {"interface": "codex-cli", "model": "gpt-5.6-sol"},
        "tools": [],
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": f"answer:{user_content}"},
        ],
    }
    row["content_sha256"] = trajectory_fingerprint(row)
    return row


def _batch(root: Path, rows: list[dict]) -> None:
    root.mkdir()
    accepted = root / "accepted.jsonl"
    accepted.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "accepted": len(rows),
                "accepted_sha256": sha256(accepted),
            }
        ),
        encoding="utf-8",
    )


def test_merge_preserves_unique_verified_rows(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _batch(first, [_row("run-a", "first")])
    _batch(second, [_row("run-b", "second")])

    rows, report = merge_batches([second, first])

    assert len(rows) == 2
    assert report["status"] == "PASS"
    assert report["exact_content_duplicates_removed"] == 0
    assert report["spark_used"] is False


def test_merge_fails_closed_on_manifest_hash_drift(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _batch(first, [_row("run-a", "first")])
    _batch(second, [_row("run-b", "second")])
    (second / "accepted.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="accepted hash drift"):
        merge_batches([first, second])


def test_merge_deduplicates_identical_visible_trajectory_with_distinct_lineage(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_row = _row("run-a", "same visible trajectory")
    second_row = _row("run-b", "same visible trajectory")
    _batch(first, [first_row])
    _batch(second, [second_row])

    rows, report = merge_batches([second, first])

    expected = min((first_row, second_row), key=stable_row_sha256)
    assert rows == [expected]
    assert report["input_rows"] == 2
    assert report["merged_rows"] == 1
    assert report["exact_content_duplicates_removed"] == 1
    assert report["duplicate_content_metadata_variants"] == 1
    assert report["unique_run_ids"] == 2


def test_merge_fails_closed_on_stale_content_fingerprint(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    stale = _row("run-a", "first")
    stale["messages"][-1]["content"] = "tampered after fingerprinting"
    _batch(first, [stale])
    _batch(second, [_row("run-b", "second")])

    with pytest.raises(RuntimeError, match="stale content fingerprint"):
        merge_batches([first, second])


def test_merge_accepts_explicitly_allowlisted_spark_without_erasing_identity(
    tmp_path: Path,
) -> None:
    codex = tmp_path / "codex"
    spark = tmp_path / "spark"
    codex_row = _row("run-codex", "codex visible trajectory")
    spark_row = _row("run-spark", "spark visible trajectory")
    spark_row["source_dataset"] = "spark_hermes_teacher_v1"
    spark_row["teacher"] = {
        "interface": "codex-spark-cli",
        "model": "gpt-5.3-codex-spark",
    }
    spark_row["content_sha256"] = trajectory_fingerprint(spark_row)
    _batch(codex, [codex_row])
    _batch(spark, [spark_row])

    rows, report = merge_batches(
        [codex, spark],
        allowed_source_datasets={
            "codex_hermes_teacher_v1",
            "spark_hermes_teacher_v1",
        },
        allowed_teacher_identities={
            ("codex_hermes_teacher_v1", "codex-cli", "gpt-5.6-sol"),
            (
                "spark_hermes_teacher_v1",
                "codex-spark-cli",
                "gpt-5.3-codex-spark",
            ),
        },
    )

    assert len(rows) == 2
    assert report["spark_used"] is True
    assert report["teacher_interface"] == "mixed"
    assert report["teacher_identities"] == {
        "codex_hermes_teacher_v1|codex-cli|gpt-5.6-sol": 1,
        "spark_hermes_teacher_v1|codex-spark-cli|gpt-5.3-codex-spark": 1,
    }
