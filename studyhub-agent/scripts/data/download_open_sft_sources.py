#!/usr/bin/env python3
"""Download and verify the open-source SFT bootstrap inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import time
import urllib.request
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, expected: str | None) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if expected is not None and sha256(path) != expected:
        raise RuntimeError(f"Checksum mismatch: {path}")


def download_url(url: str, target: Path, proxy: str, retries: int = 8) -> None:
    if target.is_file():
        return
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with opener.open(url, timeout=60) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            partial.replace(target)
            return
        except Exception:
            partial.unlink(missing_ok=True)
            if attempt == retries:
                raise
            time.sleep(min(2**attempt, 30))


def safe_extract_qasper(archive: Path, target_dir: Path) -> None:
    expected = {"qasper-train-v0.3.json", "qasper-dev-v0.3.json", "README.md"}
    if all((target_dir / name).is_file() for name in expected):
        return
    with tarfile.open(archive, "r:gz") as bundle:
        names = set(bundle.getnames())
        if not names.issubset(expected):
            raise RuntimeError(f"Unexpected QASPER archive members: {sorted(names - expected)}")
        bundle.extractall(target_dir, filter="data")


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        type=Path,
        default=project / "data_registry/open_sft_sources.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "datasets/raw/open_source",
    )
    parser.add_argument("--proxy", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    proxy = args.proxy or registry["default_proxy"]
    os.environ.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy)

    from huggingface_hub import hf_hub_download

    manifest: dict[str, object] = {
        "schema_version": "studyhub.raw-download-manifest.v1",
        "registry": str(args.registry.resolve()),
        "sources": [],
    }
    for source in registry["sources"]:
        source_dir = args.output / source["id"]
        source_dir.mkdir(parents=True, exist_ok=True)
        if source["repository"]:
            for filename in source["files"]:
                hf_hub_download(
                    repo_id=source["repository"],
                    filename=filename,
                    repo_type="dataset",
                    revision=source["revision"],
                    local_dir=source_dir,
                )
        else:
            filename = next(iter(source["files"]))
            download_url(source["download_url"], source_dir / filename, proxy)

        verified = {}
        for filename, expected in source["files"].items():
            path = source_dir / filename
            verify(path, expected)
            verified[filename] = sha256(path)
        if source["id"] == "qasper":
            safe_extract_qasper(source_dir / "qasper-train-dev-v0.3.tgz", source_dir)
        manifest["sources"].append(
            {"id": source["id"], "revision": source["revision"], "files": verified}
        )

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "download_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
