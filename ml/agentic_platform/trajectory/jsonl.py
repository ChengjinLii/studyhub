"""Dependency-free readers for Transition/Model-I/O JSONL exports."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any


class TrajectoryDataError(ValueError):
    pass


class TrajectoryJsonlReader:
    """Read already-authorized offline exports without re-tokenizing them."""

    _TRAJECTORY_ID = re.compile(r"^trajectory_[0-9a-f]{40}$")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def load_manifest(self, trajectory_id: str) -> dict[str, Any]:
        path = self._path("manifests", trajectory_id, ".json")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrajectoryDataError("invalid trajectory manifest") from exc
        if not isinstance(raw, dict):
            raise TrajectoryDataError("trajectory manifest must be a JSON object")
        return raw

    def iter_transitions(self, trajectory_id: str) -> Iterator[dict[str, Any]]:
        yield from self._read_jsonl(self._path("transitions", trajectory_id, ".jsonl"))

    def iter_model_io(self, trajectory_id: str) -> Iterator[dict[str, Any]]:
        yield from self._read_jsonl(self._path("model_io", trajectory_id, ".jsonl"))

    def _path(self, category: str, trajectory_id: str, suffix: str) -> Path:
        if not self._TRAJECTORY_ID.fullmatch(trajectory_id):
            raise TrajectoryDataError("invalid trajectory ID")
        return self.root / category / f"{trajectory_id}{suffix}"

    @staticmethod
    def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise TrajectoryDataError("trajectory JSONL is unavailable") from exc
        for line in lines:
            if not line.strip():
                raise TrajectoryDataError("trajectory JSONL contains a blank line")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrajectoryDataError("trajectory JSONL contains invalid JSON") from exc
            if not isinstance(value, Mapping):
                raise TrajectoryDataError("trajectory JSONL rows must be JSON objects")
            yield dict(value)
