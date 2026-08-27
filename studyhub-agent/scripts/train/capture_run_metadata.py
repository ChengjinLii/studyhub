#!/usr/bin/env python3
"""Capture reproducibility and resource metadata around an AReaL run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def command(*args: str) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    return result.stdout.strip()


def command_bytes(*args: str) -> bytes:
    result = subprocess.run(args, check=False, capture_output=True)
    return result.stdout


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "bytes": stat.st_size,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
    }


def load_hash_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"schema_version": "studyhub.local-file-hash-cache.v1", "files": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "studyhub.local-file-hash-cache.v1":
        raise RuntimeError(f"unsupported model hash cache: {path}")
    if not isinstance(value.get("files"), dict):
        raise RuntimeError(f"invalid model hash cache: {path}")
    return value


def cached_sha256(path: Path, cache: dict[str, Any]) -> tuple[str, str]:
    resolved = str(path.resolve())
    identity = file_identity(path)
    cached = cache["files"].get(resolved)
    if (
        isinstance(cached, dict)
        and cached.get("identity") == identity
        and isinstance(cached.get("sha256"), str)
        and len(cached["sha256"]) == 64
    ):
        return cached["sha256"], "verified_stat_cache"
    digest = sha256(path)
    cache["files"][resolved] = {"identity": identity, "sha256": digest}
    return digest, "computed"


def save_hash_cache(path: Path | None, cache: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def package_versions() -> dict[str, str]:
    names = ["areal", "torch", "transformers", "datasets", "peft", "tokenizers", "pyarrow"]
    versions = {name: importlib.metadata.version(name) for name in names}
    versions.update(
        {
            "python": platform.python_version(),
            "python_executable": str(Path(sys.executable).resolve()),
        }
    )
    try:
        import torch

        versions["cuda_runtime"] = str(torch.version.cuda)
    except ImportError:
        versions["cuda_runtime"] = "unavailable"
    return versions


def start(args: argparse.Namespace) -> None:
    project = args.project.resolve()
    repository = project.parent
    model = args.model.resolve()
    weight_files = sorted(model.glob("*.safetensors"))
    hash_cache = load_hash_cache(args.model_hash_cache)
    weight_records = []
    cache_sources: dict[str, int] = {"computed": 0, "verified_stat_cache": 0}
    for path in weight_files:
        digest, source = cached_sha256(path, hash_cache)
        cache_sources[source] += 1
        weight_records.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": digest,
                "hash_source": source,
            }
        )
    save_hash_cache(args.model_hash_cache, hash_cache)
    dirty_patch = command_bytes("git", "-C", str(repository), "diff", "--binary", "HEAD")
    untracked = command("git", "-C", str(repository), "ls-files", "--others", "--exclude-standard").splitlines()
    untracked_hashes = {}
    for relative in untracked:
        path = repository / relative
        if path.is_file():
            untracked_hashes[relative] = sha256(path)
    metadata: dict[str, Any] = {
        "schema_version": "studyhub.areal-run-metadata.v1",
        "run_mode": args.run_mode,
        "started_at": now(),
        "project": str(project),
        "git": {
            "commit": command("git", "-C", str(repository), "rev-parse", "HEAD"),
            "branch": command("git", "-C", str(repository), "branch", "--show-current"),
            "status": command("git", "-C", str(repository), "status", "--short"),
            "dirty_patch_sha256": sha256_bytes(dirty_patch),
            "dirty_patch_bytes": len(dirty_patch),
            "untracked_file_sha256": untracked_hashes,
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
            "weight_files": weight_records,
            "hash_cache": {
                "path": str(args.model_hash_cache.resolve()) if args.model_hash_cache else None,
                "sources": cache_sources,
                "validation": "device+inode+bytes+mtime_ns+ctime_ns",
            },
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
            "physical_gpus": args.gpu,
            "max_used_mib": args.max_used_mib,
            "min_free_mib": args.min_free_mib,
            "foreign_process_policy": "stop only the StudyHub process group when an unrelated GPU process appears",
        },
        "log_file": str(args.log_file.resolve()),
        "gpu_csv": str(args.gpu_csv.resolve()),
    }
    if args.data_card:
        data_card = json.loads(args.data_card.read_text(encoding="utf-8"))
        metadata["data_card"] = {
            "path": str(args.data_card.resolve()),
            "sha256": sha256(args.data_card),
            "content": data_card,
        }
        metadata["dataset_release"] = {
            "dataset_id": data_card.get("dataset_id"),
            "release_status": data_card.get("status"),
            "final_audit_status": data_card.get("audit", {}).get("status"),
            "tokenization_stage_status": metadata["dataset_manifest"].get("status"),
            "note": (
                "The tokenization manifest is an immutable stage record; the data card "
                "is the final audited release decision."
            ),
        }
    if args.benchmark_manifest:
        benchmark_manifest = json.loads(args.benchmark_manifest.read_text(encoding="utf-8"))
        metadata["benchmark"] = {
            "path": str(args.benchmark_manifest.resolve()),
            "sha256": sha256(args.benchmark_manifest),
            "version": benchmark_manifest.get("benchmark_version"),
            "revision": benchmark_manifest.get("benchmark_revision"),
            "status": benchmark_manifest.get("status"),
            "training_use": "lineage_and_post_training_evaluation_only",
            "sealed_content_used": False,
        }
    if args.authorization:
        authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
        metadata["run_authorization"] = {
            "path": str(args.authorization.resolve()),
            "sha256": sha256(args.authorization),
            "authorization_id": authorization.get("authorization_id"),
            "status": authorization.get("status"),
            "scope": authorization.get("scope"),
            "budget": authorization.get("budget"),
        }
    if args.hermes_lock:
        metadata["hermes_upstream"] = json.loads(args.hermes_lock.read_text(encoding="utf-8"))
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
    parser.add_argument("--data-card", type=Path)
    parser.add_argument("--benchmark-manifest", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--model-hash-cache", type=Path)
    parser.add_argument("--areal-lock", type=Path)
    parser.add_argument("--hermes-lock", type=Path)
    parser.add_argument("--gpu", default="0")
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
