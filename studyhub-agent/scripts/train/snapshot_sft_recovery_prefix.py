#!/usr/bin/env python3
"""Atomically branch one completed AReaL recovery checkpoint for a restart Gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _checkpoint_inventory(checkpoint: Path) -> dict[str, Any]:
    files = sorted(path for path in checkpoint.rglob("*") if path.is_file())
    metadata = checkpoint / ".metadata"
    return {
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "metadata_sha256": _sha256(metadata),
        "relative_files": [str(path.relative_to(checkpoint)) for path in files],
    }


def snapshot_prefix(
    source_root: Path,
    target_root: Path,
    output: Path,
    *,
    expected_global_step: int,
) -> dict[str, Any]:
    source_recover_info = source_root / "recover_info"
    source_checkpoint = source_root / "default" / "recover_checkpoint"
    target_recover_info = target_root / "recover_info"
    target_checkpoint = target_root / "default" / "recover_checkpoint"

    if target_root.exists():
        raise RuntimeError(f"shared-prefix target already exists: {target_root}")
    step_info = json.loads(
        (source_recover_info / "step_info.json").read_text(encoding="utf-8")
    )
    if int(step_info.get("global_step", -1)) != expected_global_step:
        raise RuntimeError(
            "unexpected prefix global step: "
            f"{step_info.get('global_step')} != {expected_global_step}"
        )
    if not (source_checkpoint / ".metadata").is_file():
        raise RuntimeError(f"incomplete DCP checkpoint: {source_checkpoint}")

    target_checkpoint.parent.mkdir(parents=True, exist_ok=False)
    os.rename(source_checkpoint, target_checkpoint)
    shutil.copytree(source_recover_info, target_recover_info)

    copied_step = json.loads(
        (target_recover_info / "step_info.json").read_text(encoding="utf-8")
    )
    if copied_step != step_info:
        raise RuntimeError("recover_info changed while the prefix was being branched")

    result = {
        "schema_version": "studyhub.sft-shared-prefix.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS",
        "method": "atomic_directory_rename_same_filesystem",
        "source_root": str(source_root.resolve()),
        "target_root": str(target_root.resolve()),
        "step_info": step_info,
        "checkpoint": _checkpoint_inventory(target_checkpoint),
        "recover_info_files": {
            path.name: _sha256(path)
            for path in sorted(target_recover_info.iterdir())
            if path.is_file()
        },
    }
    _write_json(output, result)
    return result


def wait_and_snapshot(
    source_root: Path,
    target_root: Path,
    output: Path,
    *,
    expected_global_step: int,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    step_path = source_root / "recover_info" / "step_info.json"
    deadline = time.monotonic() + timeout_seconds
    last_step: int | None = None
    while time.monotonic() < deadline:
        try:
            value = json.loads(step_path.read_text(encoding="utf-8"))
            last_step = int(value["global_step"])
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            time.sleep(poll_seconds)
            continue
        if last_step == expected_global_step:
            return snapshot_prefix(
                source_root,
                target_root,
                output,
                expected_global_step=expected_global_step,
            )
        if last_step > expected_global_step:
            raise RuntimeError(
                f"missed shared-prefix checkpoint {expected_global_step}; observed {last_step}"
            )
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"timed out waiting for global step {expected_global_step}; last={last_step}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-global-step", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = wait_and_snapshot(
            args.source_root,
            args.target_root,
            args.output,
            expected_global_step=args.expected_global_step,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except Exception as exc:
        result = {
            "schema_version": "studyhub.sft-shared-prefix.v1",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
