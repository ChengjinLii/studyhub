#!/usr/bin/env python3
"""Merge verified Codex-to-Hermes batches without weakening their lineage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from studyhub_agent.trajectory.runtime_sft import trajectory_fingerprint  # noqa: E402

DEFAULT_SOURCE_DATASETS = {"codex_hermes_teacher_v1"}
DEFAULT_TEACHER_IDENTITIES = {
    ("codex_hermes_teacher_v1", "codex-cli", "gpt-5.6-sol")
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"expected object at {path}:{line_number}")
            rows.append(value)
    return rows


def stable_row_sha256(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def merge_batches(
    roots: list[Path],
    *,
    allowed_source_datasets: set[str] | None = None,
    allowed_teacher_identities: set[tuple[str, str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(roots) < 2:
        raise RuntimeError("at least two verified teacher batches are required")
    allowed_source_datasets = allowed_source_datasets or DEFAULT_SOURCE_DATASETS
    allowed_teacher_identities = allowed_teacher_identities or DEFAULT_TEACHER_IDENTITIES
    rows_by_content: dict[str, tuple[str, dict[str, Any]]] = {}
    run_ids: dict[str, str] = {}
    duplicate_content = 0
    duplicate_metadata_variants = 0
    inputs = []
    family_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    source_groups: Counter[str] = Counter()
    teacher_identities: Counter[str] = Counter()

    for root in sorted(path.resolve() for path in roots):
        manifest_path = root / "manifest.json"
        accepted_path = root / "accepted.jsonl"
        if not manifest_path.is_file() or not accepted_path.is_file():
            raise FileNotFoundError(f"incomplete verified teacher batch: {root}")
        manifest = read_json(manifest_path)
        if manifest.get("status") != "PASS":
            raise RuntimeError(f"teacher batch is not PASS: {root}")
        actual_accepted_sha = sha256(accepted_path)
        if manifest.get("accepted_sha256") != actual_accepted_sha:
            raise RuntimeError(f"accepted hash drift: {root}")
        batch_rows = read_jsonl(accepted_path)
        if len(batch_rows) != int(manifest.get("accepted", -1)):
            raise RuntimeError(f"accepted row count drift: {root}")
        inputs.append(
            {
                "root": str(root),
                "manifest_sha256": sha256(manifest_path),
                "accepted_sha256": actual_accepted_sha,
                "accepted_rows": len(batch_rows),
            }
        )
        for row in batch_rows:
            source_dataset = str(row.get("source_dataset", ""))
            if source_dataset not in allowed_source_datasets:
                raise RuntimeError("unexpected teacher source_dataset")
            teacher = row.get("teacher", {})
            identity = (
                source_dataset,
                str(teacher.get("interface", "")),
                str(teacher.get("model", "")),
            )
            if identity not in allowed_teacher_identities:
                raise RuntimeError("unapproved teacher identity in verified batch")
            if row.get("quality_tier") not in {
                "teacher_verified_complete",
                "teacher_repaired_complete",
            }:
                raise RuntimeError("unapproved teacher quality tier")
            run_id = str(row.get("source_id", ""))
            if not run_id:
                raise RuntimeError("verified teacher row has no source_id")
            row_sha = stable_row_sha256(row)
            previous_run_sha = run_ids.setdefault(run_id, row_sha)
            if previous_run_sha != row_sha:
                raise RuntimeError(f"run ID collision with different content: {run_id}")
            content = str(row.get("content_sha256", ""))
            if len(content) != 64:
                raise RuntimeError("verified teacher row has no valid content fingerprint")
            if trajectory_fingerprint(row) != content:
                raise RuntimeError(f"verified teacher row has a stale content fingerprint: {run_id}")
            previous = rows_by_content.get(content)
            if previous is not None:
                duplicate_content += 1
                duplicate_metadata_variants += int(previous[0] != row_sha)
                # The fingerprint covers normalized tools and messages, while run IDs,
                # source groups, and provenance intentionally remain outside it. Keep
                # one deterministic representative without treating metadata-only
                # differences as a cryptographic collision.
                if row_sha < previous[0]:
                    rows_by_content[content] = (row_sha, row)
                continue
            rows_by_content[content] = (row_sha, row)

    merged = [entry[1] for entry in rows_by_content.values()]
    merged.sort(key=lambda row: hashlib.sha256(f"20260827:{row['content_sha256']}".encode()).hexdigest())
    for row in merged:
        family_counts[str(row.get("task_family", "unknown"))] += 1
        quality_counts[str(row.get("quality_tier", "unknown"))] += 1
        teacher = row.get("teacher", {})
        teacher_identities[
            "|".join(
                (
                    str(row.get("source_dataset", "")),
                    str(teacher.get("interface", "")),
                    str(teacher.get("model", "")),
                )
            )
        ] += 1
        for group in set(map(str, row.get("source_group_ids", []))):
            source_groups[group] += 1
    single_identity = None
    if len(teacher_identities) == 1:
        single_identity = next(iter(teacher_identities)).split("|", maxsplit=2)
    report = {
        "schema_version": "studyhub.codex-hermes-teacher-merge.v1",
        "status": "PASS",
        "teacher_interface": single_identity[1] if single_identity else "mixed",
        "teacher_model": single_identity[2] if single_identity else "mixed",
        "teacher_identities": dict(sorted(teacher_identities.items())),
        "inputs": inputs,
        "input_rows": sum(item["accepted_rows"] for item in inputs),
        "merged_rows": len(merged),
        "exact_content_duplicates_removed": duplicate_content,
        "duplicate_content_metadata_variants": duplicate_metadata_variants,
        "unique_run_ids": len(run_ids),
        "unique_source_groups": len(source_groups),
        "largest_source_group_rows": max(source_groups.values(), default=0),
        "family_counts": dict(sorted(family_counts.items())),
        "quality_tiers": dict(sorted(quality_counts.items())),
        "sealed_used": False,
        "spark_used": any(
            "|codex-spark-cli|" in identity for identity in teacher_identities
        ),
    }
    return merged, report


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", action="append", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--program", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = None
    identities = None
    if args.program is not None:
        gate = read_json(args.program)["teacher_gate"]
        sources = set(gate.get("source_datasets", [gate.get("source_dataset")]))
        sources.discard(None)
        identities = {
            (
                str(item["source_dataset"]),
                str(item["interface"]),
                str(item["model"]),
            )
            for item in gate.get("allowed_teacher_identities", [])
        }
        if not sources or not identities:
            raise RuntimeError("teacher program has no explicit source/identity allowlist")
    rows, report = merge_batches(
        args.input_root,
        allowed_source_datasets=sources,
        allowed_teacher_identities=identities,
    )
    output = args.output_root.resolve()
    accepted = output / "accepted.jsonl"
    write_jsonl(accepted, rows)
    report["accepted_sha256"] = sha256(accepted)
    manifest = output / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest.with_suffix(".json.partial")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
