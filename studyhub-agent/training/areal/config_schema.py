from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

AREAL_CONFIG_VERSION = "studyhub.areal.config.v1"
ALGORITHMS = frozenset({"sft", "grpo", "opd", "kdrl", "best_of_n"})


def _required_text(value: Any, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


@dataclass(frozen=True, slots=True)
class ModelConfig:
    name_or_path: str
    tokenizer_path: str
    dtype: str
    max_sequence_length: int


@dataclass(frozen=True, slots=True)
class DataConfig:
    train_path: str
    eval_path: str
    trajectory_schema: str


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    output_dir: str
    seed: int
    per_device_batch_size: int
    gradient_accumulation_steps: int
    gradient_checkpointing: bool
    requires_cuda: bool


@dataclass(frozen=True, slots=True)
class AlgorithmConfig:
    name: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    schema_version: str
    job_name: str
    model: ModelConfig
    data: DataConfig
    runtime: RuntimeConfig
    algorithm: AlgorithmConfig

    def __post_init__(self) -> None:
        if self.schema_version != AREAL_CONFIG_VERSION:
            raise ValueError(f"unsupported AReaL config schema: {self.schema_version}")
        if self.algorithm.name not in ALGORITHMS:
            raise ValueError(f"unsupported training algorithm: {self.algorithm.name}")
        if self.model.max_sequence_length < 512:
            raise ValueError("max_sequence_length must be at least 512")
        if self.runtime.seed < 0:
            raise ValueError("runtime seed must be non-negative")
        if self.runtime.per_device_batch_size < 1 or self.runtime.gradient_accumulation_steps < 1:
            raise ValueError("batch and accumulation sizes must be positive")
        if self.data.trajectory_schema != "studyhub.trajectory.v1":
            raise ValueError("training data must use studyhub.trajectory.v1")


def load_training_config(path: str | Path) -> TrainingConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("training configuration must be an object")
    model = dict(payload.get("model") or {})
    data = dict(payload.get("data") or {})
    runtime = dict(payload.get("runtime") or {})
    algorithm = dict(payload.get("algorithm") or {})
    return TrainingConfig(
        schema_version=_required_text(payload.get("schema_version"), "schema_version"),
        job_name=_required_text(payload.get("job_name"), "job_name"),
        model=ModelConfig(
            name_or_path=_required_text(model.get("name_or_path"), "model.name_or_path"),
            tokenizer_path=_required_text(model.get("tokenizer_path"), "model.tokenizer_path"),
            dtype=_required_text(model.get("dtype"), "model.dtype"),
            max_sequence_length=int(model.get("max_sequence_length", 0)),
        ),
        data=DataConfig(
            train_path=_required_text(data.get("train_path"), "data.train_path"),
            eval_path=_required_text(data.get("eval_path"), "data.eval_path"),
            trajectory_schema=_required_text(data.get("trajectory_schema"), "data.trajectory_schema"),
        ),
        runtime=RuntimeConfig(
            output_dir=_required_text(runtime.get("output_dir"), "runtime.output_dir"),
            seed=int(runtime.get("seed", -1)),
            per_device_batch_size=int(runtime.get("per_device_batch_size", 0)),
            gradient_accumulation_steps=int(runtime.get("gradient_accumulation_steps", 0)),
            gradient_checkpointing=bool(runtime.get("gradient_checkpointing", False)),
            requires_cuda=bool(runtime.get("requires_cuda", True)),
        ),
        algorithm=AlgorithmConfig(
            name=_required_text(algorithm.get("name"), "algorithm.name"),
            parameters=dict(algorithm.get("parameters") or {}),
        ),
    )
