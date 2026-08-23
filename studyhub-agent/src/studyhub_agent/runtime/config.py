from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from studyhub_agent.runtime.identity import ENVIRONMENTS
from studyhub_agent.runtime.profile import AgentProfile


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    name: str
    artifact_root: str
    fixture_mode: bool
    allow_network: bool

    def __post_init__(self) -> None:
        if self.name not in ENVIRONMENTS:
            raise ValueError(f"unsupported environment config: {self.name}")
        if not self.artifact_root.strip():
            raise ValueError("artifact_root is required")


@dataclass(slots=True)
class Phase1Config:
    profile: AgentProfile
    environment: EnvironmentConfig

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile.to_dict(), "environment": asdict(self.environment)}


def _read_yaml(path: str | Path) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return value


def load_phase1_config(agent_path: str | Path, environment_path: str | Path) -> Phase1Config:
    agent_data = _read_yaml(agent_path)
    env_data = _read_yaml(environment_path)
    profile_data = agent_data.get("profile")
    environment_data = env_data.get("environment")
    if not isinstance(profile_data, dict) or not isinstance(environment_data, dict):
        raise ValueError("agent and environment configuration sections are required")
    return Phase1Config(
        profile=AgentProfile.from_dict(profile_data),
        environment=EnvironmentConfig(
            name=str(environment_data["name"]),
            artifact_root=str(environment_data["artifact_root"]),
            fixture_mode=bool(environment_data["fixture_mode"]),
            allow_network=bool(environment_data["allow_network"]),
        ),
    )
