from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

EXPERIMENT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = EXPERIMENT_ROOT.parents[1]


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    raw: dict[str, Any]
    path: Path

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name)
        if not isinstance(value, dict):
            raise ValueError(f"Missing configuration section: {name}")
        return value

    def repo_path(self, value: str) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()

    def experiment_path(self, value: str) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (EXPERIMENT_ROOT / path).resolve()


def load_config(path: str | Path) -> ExperimentConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = (EXPERIMENT_ROOT / config_path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration must be a mapping: {config_path}")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported configuration schema_version")
    return ExperimentConfig(raw=payload, path=config_path)
