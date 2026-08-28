#!/usr/bin/env python3
"""Create a verified, non-destructive snapshot of a paused AReaL checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_RECOVER_INFO = {
    "checkpoint_info.json",
    "dataloader_info.pkl",
    "evaluator_info.json",
    "saver_info.json",
    "stats_logger_info.json",
    "step_info.json",
}
TRANSIENT_MARKERS = (".partial", ".tmp", "~")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
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


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _payload_files(root: Path) -> list[Path]:
    checkpoint = root / "default" / "recover_checkpoint"
    recover_info = root / "recover_info"
    return sorted([*_files(checkpoint), *_files(recover_info)])


def _stat_inventory(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in _payload_files(root):
        stat = path.stat()
        rows.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return rows


def _hashed_inventory(root: Path) -> dict[str, Any]:
    rows = []
    digest = hashlib.sha256()
    for path in _payload_files(root):
        relative = str(path.relative_to(root))
        size = path.stat().st_size
        file_hash = _sha256(path)
        row = {"path": relative, "bytes": size, "sha256": file_hash}
        rows.append(row)
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return {
        "file_count": len(rows),
        "total_bytes": sum(row["bytes"] for row in rows),
        "tree_sha256": digest.hexdigest(),
        "files": rows,
    }


def _validate_source(source_root: Path, expected_global_step: int) -> dict[str, Any]:
    checkpoint = source_root / "default" / "recover_checkpoint"
    recover_info = source_root / "recover_info"
    if not checkpoint.is_dir() or not recover_info.is_dir():
        raise RuntimeError(f"missing checkpoint or recover_info under {source_root}")
    if not (checkpoint / ".metadata").is_file():
        raise RuntimeError(f"incomplete DCP checkpoint: {checkpoint}")

    files = _files(checkpoint) + _files(recover_info)
    if any(path.is_symlink() for path in files):
        raise RuntimeError("checkpoint snapshot refuses symbolic links")
    transient = [str(path) for path in files if any(path.name.endswith(marker) for marker in TRANSIENT_MARKERS)]
    if transient:
        raise RuntimeError(f"transient checkpoint files are still present: {transient}")
    missing = sorted(REQUIRED_RECOVER_INFO - {path.name for path in _files(recover_info)})
    if missing:
        raise RuntimeError(f"recover_info is incomplete: {missing}")

    step_info = json.loads((recover_info / "step_info.json").read_text(encoding="utf-8"))
    if int(step_info.get("global_step", -1)) != expected_global_step:
        raise RuntimeError(f"unexpected prefix global step: {step_info.get('global_step')} != {expected_global_step}")
    return step_info


def _dcp_metadata_smoke(checkpoint: Path) -> dict[str, Any]:
    from torch.distributed.checkpoint import FileSystemReader

    metadata = FileSystemReader(checkpoint).read_metadata()
    state_dict_metadata = getattr(metadata, "state_dict_metadata", {})
    planner_data = getattr(metadata, "planner_data", {})
    return {
        "status": "PASS",
        "kind": "DCP_METADATA_LOAD",
        "state_dict_metadata_entries": len(state_dict_metadata),
        "planner_data_entries": len(planner_data),
    }


def _runtime_info() -> dict[str, Any]:
    import torch

    nccl = torch.cuda.nccl.version() if torch.cuda.is_available() else None
    return {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "nccl": list(nccl) if isinstance(nccl, tuple) else nccl,
        "world_size": (
            torch.distributed.get_world_size()
            if torch.distributed.is_available() and torch.distributed.is_initialized()
            else 1
        ),
    }


def snapshot_prefix(
    source_root: Path,
    target_root: Path,
    output: Path,
    *,
    expected_global_step: int,
    stability_interval_seconds: float = 0.5,
    require_dcp_metadata_load: bool = True,
) -> dict[str, Any]:
    """Copy a source that the caller guarantees is paused at a checkpoint barrier."""

    if target_root.exists():
        raise RuntimeError(f"shared-prefix target already exists: {target_root}")
    if stability_interval_seconds < 0:
        raise ValueError("stability interval must be non-negative")
    step_info = _validate_source(source_root, expected_global_step)

    first_stat = _stat_inventory(source_root)
    time.sleep(stability_interval_seconds)
    second_stat = _stat_inventory(source_root)
    if first_stat != second_stat:
        raise RuntimeError("source checkpoint changed across stability windows")

    source_inventory = _hashed_inventory(source_root)
    source_dcp = (
        _dcp_metadata_smoke(source_root / "default" / "recover_checkpoint")
        if require_dcp_metadata_load
        else {"status": "NOT_RUN", "kind": "DCP_METADATA_LOAD"}
    )

    target_root.parent.mkdir(parents=True, exist_ok=True)
    staging = target_root.parent / f".{target_root.name}.partial-{uuid.uuid4().hex}"
    try:
        (staging / "default").mkdir(parents=True)
        shutil.copytree(
            source_root / "default" / "recover_checkpoint",
            staging / "default" / "recover_checkpoint",
            copy_function=shutil.copy2,
        )
        shutil.copytree(
            source_root / "recover_info",
            staging / "recover_info",
            copy_function=shutil.copy2,
        )

        third_stat = _stat_inventory(source_root)
        if second_stat != third_stat:
            raise RuntimeError("source checkpoint changed during non-destructive copy")
        target_inventory = _hashed_inventory(staging)
        if source_inventory != target_inventory:
            raise RuntimeError("source and target checkpoint inventories differ")
        target_dcp = (
            _dcp_metadata_smoke(staging / "default" / "recover_checkpoint")
            if require_dcp_metadata_load
            else {"status": "NOT_RUN", "kind": "DCP_METADATA_LOAD"}
        )
        staging.rename(target_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if not (source_root / "default" / "recover_checkpoint").is_dir():
        raise RuntimeError("non-destructive snapshot removed the source checkpoint")

    result = {
        "schema_version": "studyhub.sft-shared-prefix.v2",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS",
        "method": "paused_non_destructive_copy_atomic_publish",
        "source_root": str(source_root.resolve()),
        "target_root": str(target_root.resolve()),
        "caller_contract": "SOURCE_PAUSED_AT_POST_CHECKPOINT_BARRIER",
        "source_preserved": True,
        "stability": {
            "status": "PASS",
            "windows": 3,
            "interval_seconds": stability_interval_seconds,
        },
        "step_info": step_info,
        "source_inventory": source_inventory,
        "target_inventory": target_inventory,
        "inventory_equal": True,
        "dcp_metadata_load": {
            "source": source_dcp,
            "target": target_dcp,
        },
        "runtime": _runtime_info(),
    }
    _write_json(output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-global-step", type=int, required=True)
    parser.add_argument("--stability-interval-seconds", type=float, default=0.5)
    parser.add_argument(
        "--source-paused",
        action="store_true",
        help="Assert that all training ranks are blocked before their next step.",
    )
    parser.add_argument("--skip-dcp-metadata-load", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if not args.source_paused:
            raise RuntimeError("refusing an asynchronous snapshot without --source-paused")
        result = snapshot_prefix(
            args.source_root,
            args.target_root,
            args.output,
            expected_global_step=args.expected_global_step,
            stability_interval_seconds=args.stability_interval_seconds,
            require_dcp_metadata_load=not args.skip_dcp_metadata_load,
        )
    except Exception as exc:
        result = {
            "schema_version": "studyhub.sft-shared-prefix.v2",
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
