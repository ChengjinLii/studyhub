#!/usr/bin/env python3
"""Pair frozen Qwen3.5 student weights with a canonical teacher tokenizer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

TOKENIZER_ASSETS = (
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
    "vocab.json",
    "merges.txt",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_symlink(destination: Path, source: Path) -> None:
    if destination.is_symlink() and destination.resolve() == source.resolve():
        return
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            raise RuntimeError(f"refusing to replace overlay directory: {destination}")
        destination.unlink()
    destination.symlink_to(source.resolve())


def prepare_overlay(student: Path, canonical_tokenizer: Path, output: Path) -> dict[str, Any]:
    student = student.resolve()
    canonical_tokenizer = canonical_tokenizer.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    missing = [name for name in TOKENIZER_ASSETS if not (canonical_tokenizer / name).is_file()]
    if missing:
        raise RuntimeError(f"canonical tokenizer is incomplete: {missing}")

    for source in student.iterdir():
        if source.name in {*TOKENIZER_ASSETS, ".cache"}:
            continue
        _replace_symlink(output / source.name, source)
    for name in TOKENIZER_ASSETS:
        _replace_symlink(output / name, canonical_tokenizer / name)

    student_manifest = json.loads((student / "studyhub_download_manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "studyhub.qwen35-canonical-tokenizer-overlay.v1",
        "status": "LOCKED",
        "student_weights": {
            "path": str(student),
            "repository": student_manifest["repository"],
            "revision": student_manifest["revision"],
            "config_sha256": sha256(student / "config.json"),
            "weight_shards": [
                {
                    "name": row["name"],
                    "bytes": (student / row["name"]).stat().st_size,
                    "sha256": sha256(student / row["name"]),
                }
                for row in student_manifest["weight_shards"]
            ],
        },
        "canonical_tokenizer": {
            "path": str(canonical_tokenizer),
            "assets": {
                name: {
                    "bytes": (canonical_tokenizer / name).stat().st_size,
                    "sha256": sha256(canonical_tokenizer / name),
                }
                for name in TOKENIZER_ASSETS
            },
        },
        "overlay": str(output),
        "weight_files_are_symlinks": True,
        "tokenizer_files_are_symlinks": True,
    }
    (output / "studyhub_tokenizer_overlay_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student", type=Path, required=True)
    parser.add_argument("--canonical-tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()

    manifest = prepare_overlay(args.student, args.canonical_tokenizer, args.output)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
