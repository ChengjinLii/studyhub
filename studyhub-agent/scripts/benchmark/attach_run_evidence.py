#!/usr/bin/env python3
"""Attach guarded-launch GPU telemetry to one Benchmark v1 run manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_gpu_summary(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise RuntimeError(f"GPU telemetry is empty: {path}")

    gpu_key = next((key for key in rows[0] if key.casefold() in {"gpu", "index", "gpu_index"}), None)
    used_key = next((key for key in rows[0] if "used" in key.casefold()), None)
    if gpu_key is None or used_key is None:
        raise RuntimeError(f"unsupported GPU telemetry columns: {sorted(rows[0])}")

    peaks: dict[str, float] = {}
    for row in rows:
        gpu = str(row[gpu_key])
        peaks[gpu] = max(peaks.get(gpu, 0.0), float(row[used_key]))
    return {
        "samples": len(rows),
        "peak_used_mib_by_gpu": {key: round(value, 3) for key, value in sorted(peaks.items())},
    }


def attach(manifest_path: Path, telemetry_path: Path, launcher_log: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("artifacts", {})["gpu_telemetry"] = {
        "path": str(telemetry_path.resolve()),
        "sha256": sha256(telemetry_path),
        **load_gpu_summary(telemetry_path),
    }
    manifest["artifacts"]["launcher_log"] = {
        "path": str(launcher_log.resolve()),
        "sha256": sha256(launcher_log),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gpu-telemetry", type=Path, required=True)
    parser.add_argument("--launcher-log", type=Path, required=True)
    args = parser.parse_args()
    manifest = attach(args.manifest.resolve(), args.gpu_telemetry.resolve(), args.launcher_log.resolve())
    print(json.dumps(manifest["artifacts"]["gpu_telemetry"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
