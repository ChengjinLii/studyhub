#!/usr/bin/env python3
"""Remove one ephemeral runtime secret from text artifacts for a single trial."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".txt", ".yaml", ".yml"}
MAX_TEXT_BYTES = 64 * 1024 * 1024
REDACTION = b"<redacted-ephemeral-admin-key>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def candidate_files(root: Path, trial: str) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and trial in str(path.relative_to(root))
        and path.suffix.lower() in TEXT_SUFFIXES
        and path.stat().st_size <= MAX_TEXT_BYTES
    )


def redact(root: Path, trial: str, secret: bytes) -> tuple[int, int, list[str]]:
    files_changed = 0
    replacements = 0
    changed_paths = []
    for path in candidate_files(root, trial):
        content = path.read_bytes()
        count = content.count(secret)
        if not count:
            continue
        path.write_bytes(content.replace(secret, REDACTION))
        files_changed += 1
        replacements += count
        changed_paths.append(str(path.relative_to(root)))
    return files_changed, replacements, changed_paths


def main() -> int:
    args = parse_args()
    secret = os.environ.get("STUDYHUB_SECRET_TO_REDACT", "").encode()
    if len(secret) < 32:
        raise RuntimeError("refusing to redact an empty or implausibly short secret")
    files_changed, replacements, changed_paths = redact(
        args.artifacts_root.resolve(), args.trial, secret
    )
    summary = {
        "schema_version": "studyhub.trial-secret-redaction.v1",
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trial": args.trial,
        "files_changed": files_changed,
        "replacements": replacements,
        "paths": changed_paths,
        "secret_retained": False,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
