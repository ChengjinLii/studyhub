#!/usr/bin/env python3
"""Fetch pinned external benchmark sources into an ignored, reproducible cache."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from external_benchmarks.registry import load_registry  # noqa: E402 - standalone script bootstraps project root

LOCK_SCHEMA = "studyhub.external-benchmark-lock.v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_git(arguments: list[str], *, cwd: Path | None = None, capture_bytes: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=not capture_bytes,
    )
    return completed.stdout if capture_bytes else completed.stdout.strip()


def ensure_bare_cache(path: Path, upstream: str, *, offline: bool) -> None:
    if not path.exists():
        if offline:
            raise RuntimeError(f"offline cache is missing: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        run_git(["init", "--bare", str(path)])
        run_git(["--git-dir", str(path), "remote", "add", "origin", upstream])
    configured = run_git(["--git-dir", str(path), "remote", "get-url", "origin"])
    if configured != upstream:
        raise RuntimeError(f"upstream drift for {path.name}: {configured!r} != {upstream!r}")


def resolve_revision(path: Path, expected_commit: str, *, offline: bool) -> tuple[str, str]:
    if not offline:
        run_git(["--git-dir", str(path), "fetch", "--depth=1", "origin", expected_commit])
    try:
        resolved = str(run_git(["--git-dir", str(path), "rev-parse", f"{expected_commit}^{{commit}}"])).lower()
    except subprocess.CalledProcessError as error:
        mode = "offline cache" if offline else "upstream fetch"
        raise RuntimeError(f"{mode} does not contain {expected_commit}") from error
    if resolved != expected_commit:
        raise RuntimeError(f"resolved commit drift: {resolved} != {expected_commit}")
    tree = str(run_git(["--git-dir", str(path), "rev-parse", f"{expected_commit}^{{tree}}"])).lower()
    return resolved, tree


def git_file(path: Path, commit: str, relative: str) -> bytes:
    try:
        value = run_git(
            ["--git-dir", str(path), "show", f"{commit}:{relative}"],
            capture_bytes=True,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"pinned source is missing expected path: {relative}") from error
    assert isinstance(value, bytes)
    return value


def safe_export(path: Path, commit: str, destination: Path, marker: dict[str, str]) -> None:
    marker_path = destination / ".studyhub-external-lock.json"
    if marker_path.is_file() and json.loads(marker_path.read_text(encoding="utf-8")) == marker:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "source"
        staging.mkdir()
        archive = run_git(
            ["--git-dir", str(path), "archive", "--format=tar", commit],
            capture_bytes=True,
        )
        assert isinstance(archive, bytes)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
            for member in stream.getmembers():
                target = (staging / member.name).resolve()
                if staging.resolve() not in target.parents and target != staging.resolve():
                    raise RuntimeError(f"unsafe archive member: {member.name}")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.issym():
                    if Path(member.linkname).is_absolute():
                        raise RuntimeError(f"unsafe absolute symlink: {member.name} -> {member.linkname}")
                    link_target = (target.parent / member.linkname).resolve()
                    if staging.resolve() not in link_target.parents and link_target != staging.resolve():
                        raise RuntimeError(f"unsafe escaping symlink: {member.name} -> {member.linkname}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(member.linkname)
                    continue
                if not member.isfile():
                    raise RuntimeError(f"unsupported archive member type: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = stream.extractfile(member)
                if source is None:
                    raise RuntimeError(f"could not extract archive member: {member.name}")
                target.write_bytes(source.read())
        (staging / ".studyhub-external-lock.json").write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)


def fetch_one(
    name: str,
    row: dict[str, Any],
    *,
    cache_root: Path,
    offline: bool,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    commit = str(row["revision"]["resolved_commit"])
    bare = cache_root / "git-cache" / f"{name}.git"
    ensure_bare_cache(bare, str(row["upstream"]), offline=offline)
    resolved, tree = resolve_revision(bare, commit, offline=offline)
    hashes = {relative: sha256_bytes(git_file(bare, commit, relative)) for relative in row["expected_paths"]}
    export_allowed = bool(row.get("export_allowed"))
    source_dir = cache_root / "sources" / name / commit
    if export_allowed:
        safe_export(
            bare,
            commit,
            source_dir,
            {"benchmark": name, "resolved_commit": resolved, "tree": tree},
        )
    license_status = str(row["license"]["status"])
    status = "FETCHED" if license_status == "verified" else "LICENSE_REVIEW_REQUIRED"
    stable_identity = {
        "resolved_commit": resolved,
        "git_tree": tree,
        "artifact_hashes": hashes,
    }
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    if previous and all(previous.get(key) == value for key, value in stable_identity.items()):
        fetched_at = str(previous["fetched_at"])
    return {
        "name": name,
        "upstream": row["upstream"],
        "revision": row["revision"]["ref"],
        "resolved_commit": resolved,
        "git_tree": tree,
        "license": row["license"],
        "fetched_at": fetched_at,
        "artifact_hashes": hashes,
        "source_exported": export_allowed,
        "source_path": str(source_dir.relative_to(cache_root.parent.parent)) if export_allowed else None,
        "data_assets": row.get("data_assets", []),
        "setup_status": status,
        "evaluator_status": "SETUP_READY" if status == "FETCHED" else status,
    }


def parse_args() -> argparse.Namespace:
    project = PROJECT_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default="all")
    parser.add_argument("--registry", type=Path, default=project / "external_benchmarks/registry.yaml")
    parser.add_argument("--lock", type=Path, default=project / "external_benchmarks/lock.json")
    parser.add_argument("--cache-root", type=Path, default=project / "artifacts/external-benchmarks")
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_registry(args.registry)
    names = list(registry["benchmarks"])
    if args.benchmark != "all":
        if args.benchmark not in registry["benchmarks"]:
            raise SystemExit(f"unknown benchmark: {args.benchmark}")
        names = [args.benchmark]
    existing: dict[str, Any] = {}
    existing_generated_at: str | None = None
    if args.lock.is_file():
        loaded = json.loads(args.lock.read_text(encoding="utf-8"))
        existing = dict(loaded.get("benchmarks", {}))
        existing_generated_at = loaded.get("generated_at")
    for name in names:
        existing[name] = fetch_one(
            name,
            registry["benchmarks"][name],
            cache_root=args.cache_root.resolve(),
            offline=args.offline,
            previous=existing.get(name),
        )
    lock_without_time = {
        "schema_version": LOCK_SCHEMA,
        "portfolio_version": registry["portfolio_version"],
        "registry_sha256": sha256_bytes(args.registry.read_bytes()),
        "benchmarks": {name: existing[name] for name in sorted(existing)},
    }
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    if args.lock.is_file():
        prior_without_time = {key: value for key, value in loaded.items() if key != "generated_at"}
        if prior_without_time == lock_without_time and existing_generated_at:
            generated_at = existing_generated_at
    lock = {**lock_without_time, "generated_at": generated_at}
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    args.lock.write_text(json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(lock, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
