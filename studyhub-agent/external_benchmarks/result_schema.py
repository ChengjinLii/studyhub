"""Shared transport and reporting schema without changing official benchmark metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ModelEndpointConfig:
    base_url: str
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 120.0
    organization_env: str | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("credentials must not be embedded in base_url")
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if not self.api_key_env.isidentifier():
            raise ValueError("api_key_env must be an environment-variable identifier")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] = ()
    temperature: float = 0.0
    max_tokens: int = 4096
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("messages must not be empty")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.temperature < 0:
            raise ValueError("temperature must be non-negative")


@dataclass(frozen=True, slots=True)
class ToolTrace:
    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    observation: Any | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if min(self.prompt_tokens, self.completion_tokens, self.total_tokens) < 0:
            raise ValueError("token usage cannot be negative")


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    finish_reason: str
    tool_trace: tuple[ToolTrace, ...] = ()
    usage: Usage = field(default_factory=Usage)
    response_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalBenchmarkResult:
    benchmark: str
    benchmark_version: str
    model: str
    model_revision: str
    adapter_revision: str
    run_id: str
    raw_metric_name: str
    raw_metric_value: float | int | str | None
    status: str
    raw_result_path: str | None = None
    cost: float | None = None
    latency_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {
            "COMPLETED",
            "FETCHED",
            "SETUP_READY",
            "SMOKE_PASS",
            "SKIPPED_NO_API_KEY",
            "SKIPPED_NO_GPU",
            "LICENSE_REVIEW_REQUIRED",
            "FAILED",
        }
        if self.status not in allowed:
            raise ValueError(f"unsupported result status: {self.status}")
        if self.cost is not None and self.cost < 0:
            raise ValueError("cost cannot be negative")
        if self.latency_seconds is not None and self.latency_seconds < 0:
            raise ValueError("latency cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
