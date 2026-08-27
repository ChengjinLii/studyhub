#!/usr/bin/env python3
"""Fail closed when commit candidates contain credential-like literals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_token": re.compile(r"(?i)(?<![A-Za-z0-9])(?:sk|tp)-[A-Za-z0-9_-]{20,}"),
    "huggingface_token": re.compile(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{20,}"),
    "github_token": re.compile(r"(?<![A-Za-z0-9])gh[opusr]_[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    "slack_token": re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,}"),
    "credential_url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
}
SAFE_FIXTURE_MATCHES = {"https://user:secret@"}


def candidate_files(repo: Path, pathspec: str) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", pathspec],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return [repo / value.decode() for value in completed.stdout.split(b"\0") if value]


def scan_file(path: Path, repo: Path, max_bytes: int) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size > max_bytes:
        return []
    raw = path.read_bytes()
    if b"\0" in raw[:8192]:
        return []
    text = raw.decode("utf-8", errors="replace")
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS.items():
            match = pattern.search(line)
            if match:
                if match.group() in SAFE_FIXTURE_MATCHES:
                    continue
                findings.append(
                    {
                        "path": str(path.relative_to(repo)),
                        "line": line_number,
                        "pattern": name,
                        "match_sha256_prefix": hashlib.sha256(match.group().encode()).hexdigest()[:12],
                    }
                )
    return findings


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    repo = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=repo)
    parser.add_argument("--pathspec", default=str(project.relative_to(repo)))
    parser.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    files = candidate_files(repo, args.pathspec)
    findings = [finding for path in files for finding in scan_file(path, repo, args.max_bytes)]
    report = {
        "schema_version": "studyhub.commit-secret-scan.v1",
        "status": "PASS" if not findings else "FAIL",
        "files_scanned": len(files),
        "findings": findings,
        "note": "Matches are reported by hash prefix; secret values are never echoed.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
