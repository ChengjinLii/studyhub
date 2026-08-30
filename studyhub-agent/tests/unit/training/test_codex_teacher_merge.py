import json
from pathlib import Path

import pytest

from scripts.data.merge_codex_hermes_teacher_datasets import merge_batches, sha256


def _row(run_id: str, content: str) -> dict:
    return {
        "source_dataset": "codex_hermes_teacher_v1",
        "source_id": run_id,
        "source_group_ids": [f"group-{run_id}"],
        "task_family": "rag_query_rewrite_citation",
        "quality_tier": "teacher_verified_complete",
        "content_sha256": content,
        "teacher": {"interface": "codex-cli", "model": "gpt-5.6-sol"},
    }


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
    _batch(first, [_row("run-a", "a" * 64)])
    _batch(second, [_row("run-b", "b" * 64)])

    rows, report = merge_batches([second, first])

    assert len(rows) == 2
    assert report["status"] == "PASS"
    assert report["exact_content_duplicates_removed"] == 0
    assert report["spark_used"] is False


def test_merge_fails_closed_on_manifest_hash_drift(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _batch(first, [_row("run-a", "a" * 64)])
    _batch(second, [_row("run-b", "b" * 64)])
    (second / "accepted.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="accepted hash drift"):
        merge_batches([first, second])
