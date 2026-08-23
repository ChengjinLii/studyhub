#!/usr/bin/env python3
"""Capture reproducibility and resource metadata around an AReaL run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def command(*args: str) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_versions() -> dict[str, str]:
    names = ["areal", "torch", "transformers", "datasets", "peft", "tokenizers", "pyarrow"]
    return {name: importlib.metadata.version(name) for name in names}


def start(args: argparse.Namespace) -> None:
    project = args.project.resolve()
    model = args.model.resolve()
    weight_files = sorted(model.glob("*.safetensors"))
    metadata: dict[str, Any] = {
        "schema_version": "studyhub.areal-run-metadata.v1",
        "run_mode": args.run_mode,
        "started_at": now(),
        "project": str(project),
        "git": {
            "commit": command("git", "-C", str(project.parent), "rev-parse", "HEAD"),
            "branch": command("git", "-C", str(project.parent), "branch", "--show-current"),
            "status": command("git", "-C", str(project.parent), "status", "--short"),
        },
        "config": {
            "path": str(args.config.resolve()),
            "sha256": sha256(args.config),
            "overrides": args.override,
        },
        "dataset_manifest": json.loads(args.dataset_manifest.read_text(encoding="utf-8")),
        "dataset_manifest_sha256": sha256(args.dataset_manifest),
        "model": {
            "path": str(model),
            "config_sha256": sha256(model / "config.json"),
            "weight_files": [
                {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
                for path in weight_files
            ],
        },
        "software": package_versions(),
        "areal_upstream": json.loads(args.areal_lock.read_text(encoding="utf-8")),
        "hardware": command(
            "nvidia-smi",
            f"--id={args.gpu}",
            "--query-gpu=index,name,uuid,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ),
        "resource_guard": {
            "physical_gpu": args.gpu,
            "max_used_mib": args.max_used_mib,
            "min_free_mib": args.min_free_mib,
            "foreign_process_policy": "stop only the StudyHub process group when a foreign owner appears",
        },
        "log_file": str(args.log_file.resolve()),
        "gpu_csv": str(args.gpu_csv.resolve()),
    }
    args.output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def finish(args: argparse.Namespace) -> None:
    metadata = json.loads(args.output.read_text(encoding="utf-8"))
    rows = []
    if args.gpu_csv.is_file():
        with args.gpu_csv.open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
    used = [int(row["memory_used_mib"]) for row in rows if row.get("memory_used_mib")]
    utilization = [int(row["utilization_gpu_pct"]) for row in rows if row.get("utilization_gpu_pct")]
    metadata["finished_at"] = now()
    metadata["exit_status"] = args.status
    metadata["resource_summary"] = {
        "samples": len(rows),
        "peak_memory_used_mib": max(used, default=None),
        "peak_utilization_gpu_pct": max(utilization, default=None),
    }
    args.output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["start", "finish"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--run-mode")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dataset-manifest", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--areal-lock", type=Path)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--max-used-mib", type=int, default=28672)
    parser.add_argument("--min-free-mib", type=int, default=60000)
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--gpu-csv", type=Path, required=True)
    parser.add_argument("--override", action="append", default=[])
    parser.add_argument("--status", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.phase == "start":
        start(args)
    else:
        finish(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
