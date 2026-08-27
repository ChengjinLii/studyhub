"""Validation and loading for the pinned external benchmark registry."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REGISTRY_SCHEMA = "studyhub.external-benchmark-registry.v1"
OFFICIAL_UPSTREAMS = {
    "bfcl": "https://github.com/ShishirPatil/gorilla.git",
    "tau2": "https://github.com/sierra-research/tau2-bench.git",
    "deepresearch_bench_ii": "https://github.com/SawyerCooper/DeepResearchBench2.git",
    "browsecomp_plus": "https://github.com/texttron/BrowseComp-Plus.git",
}
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def load_registry(path: str | Path) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("external benchmark registry must be a mapping")
    validate_registry(value)
    return value


def validate_registry(value: dict[str, Any]) -> None:
    if value.get("schema_version") != REGISTRY_SCHEMA:
        raise ValueError("unsupported external benchmark registry schema")
    benchmarks = value.get("benchmarks")
    if not isinstance(benchmarks, dict) or set(benchmarks) != set(OFFICIAL_UPSTREAMS):
        raise ValueError("registry must contain exactly the four portfolio benchmarks")
    for name, expected_upstream in OFFICIAL_UPSTREAMS.items():
        row = benchmarks[name]
        if not isinstance(row, dict) or row.get("upstream") != expected_upstream:
            raise ValueError(f"{name} does not use the approved official upstream")
        revision = row.get("revision")
        if not isinstance(revision, dict) or not _COMMIT.fullmatch(str(revision.get("resolved_commit", ""))):
            raise ValueError(f"{name} must pin a full 40-character commit")
        if revision.get("kind") not in {"commit", "tag"} or not str(revision.get("ref", "")).strip():
            raise ValueError(f"{name} has an invalid revision contract")
        license_row = row.get("license")
        if not isinstance(license_row, dict) or license_row.get("status") not in {"verified", "unconfirmed"}:
            raise ValueError(f"{name} has no explicit license status")
        if license_row.get("status") == "unconfirmed" and row.get("export_allowed") is not False:
            raise ValueError(f"{name} cannot export source while license is unconfirmed")
        paths = row.get("expected_paths")
        if not isinstance(paths, list) or not paths or any(Path(str(path)).is_absolute() for path in paths):
            raise ValueError(f"{name} expected_paths must be non-empty relative paths")
        evaluator = row.get("evaluator")
        if not isinstance(evaluator, dict) or evaluator.get("preserves_official_metrics") is not True:
            raise ValueError(f"{name} must preserve its official evaluator metrics")
