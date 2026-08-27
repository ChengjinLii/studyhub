from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]


def test_benchmark_v1_frozen_integrity() -> None:
    lock = json.loads((PROJECT / "configs/benchmark-v1-frozen-hashes.json").read_text(encoding="utf-8"))
    tracked = {
        str(path.relative_to(PROJECT))
        for path in (PROJECT / "benchmarks/studyhub-agent-v1").rglob("*")
        if path.is_file()
    }
    assert tracked == set(lock["files"])
    for relative_path, expected in lock["files"].items():
        actual = hashlib.sha256((PROJECT / relative_path).read_bytes()).hexdigest()
        assert actual == expected, relative_path
