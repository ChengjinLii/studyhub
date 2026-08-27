from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BENCHMARK_VERSION = "studyhub-agentbench-v1"
TASK_SCHEMA_VERSION = "studyhub.agentbench-task.v1"
ENVIRONMENT_SCHEMA_VERSION = "studyhub.agentbench-environment.v1"
GRADER_SCHEMA_VERSION = "studyhub.agentbench-grader.v1"

PUBLIC_FORBIDDEN_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "expected_answer",
        "expected_answers",
        "expected_call",
        "expected_calls",
        "gold_query",
        "gold_source_order",
        "gold_trajectory",
        "oracle_answer",
        "supporting_facts",
        "verifier",
        "grader",
        "rubric",
    }
)

BUDGET_TIERS: dict[str, dict[str, int]] = {
    "direct": {"max_model_turns": 3, "max_tool_calls": 1, "max_context_tokens": 4096},
    "short": {"max_model_turns": 6, "max_tool_calls": 4, "max_context_tokens": 8192},
    "extended": {"max_model_turns": 10, "max_tool_calls": 8, "max_context_tokens": 16384},
    "research": {"max_model_turns": 20, "max_tool_calls": 16, "max_context_tokens": 32768},
}


def _assert_no_forbidden_fields(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        forbidden = PUBLIC_FORBIDDEN_FIELDS & set(value)
        if forbidden:
            raise ValueError(f"public task exposes forbidden fields at {path}: {sorted(forbidden)}")
        for key, nested in value.items():
            _assert_no_forbidden_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_forbidden_fields(nested, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    task_id: str
    split: str
    capability_id: str
    secondary_capabilities: tuple[str, ...]
    difficulty: str
    language: str
    horizon_tier: str
    user_request: str
    environment_id: str
    available_tools: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    budget_tier: str
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BenchmarkTask:
        _assert_no_forbidden_fields(value)
        if value.get("schema_version") != TASK_SCHEMA_VERSION:
            raise ValueError(f"unsupported task schema: {value.get('schema_version')}")
        if value.get("benchmark_version") != BENCHMARK_VERSION:
            raise ValueError(f"unsupported benchmark version: {value.get('benchmark_version')}")
        budget_tier = str(value["budget_tier"])
        if budget_tier not in BUDGET_TIERS:
            raise ValueError(f"unknown budget tier: {budget_tier}")
        task = cls(
            task_id=str(value["task_id"]),
            split=str(value["split"]),
            capability_id=str(value["capability_id"]),
            secondary_capabilities=tuple(str(item) for item in value.get("secondary_capabilities", [])),
            difficulty=str(value["difficulty"]),
            language=str(value["language"]),
            horizon_tier=str(value["horizon_tier"]),
            user_request=str(value["user_request"]),
            environment_id=str(value["environment_id"]),
            available_tools=tuple(str(item) for item in value.get("available_tools", [])),
            hard_constraints=tuple(str(item) for item in value.get("hard_constraints", [])),
            budget_tier=budget_tier,
            metadata=dict(value.get("metadata", {})),
        )
        task.validate()
        return task

    def validate(self) -> None:
        if not self.task_id or self.task_id != self.environment_id:
            raise ValueError("task_id and environment_id must be identical and non-empty")
        if self.split not in {"regression", "development", "sealed"}:
            raise ValueError(f"invalid benchmark split: {self.split}")
        if self.difficulty not in {"easy", "medium", "hard"}:
            raise ValueError(f"invalid difficulty: {self.difficulty}")
        if self.language not in {"zh", "en"}:
            raise ValueError(f"invalid language: {self.language}")
        if self.horizon_tier not in {"1", "3", "6", "10+"}:
            raise ValueError(f"invalid horizon tier: {self.horizon_tier}")
        if len(self.user_request.strip()) < 12:
            raise ValueError(f"task request is too short: {self.task_id}")
        if len(self.available_tools) != len(set(self.available_tools)):
            raise ValueError(f"duplicate available tools: {self.task_id}")

    @property
    def budget(self) -> dict[str, int]:
        return dict(BUDGET_TIERS[self.budget_tier])

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": TASK_SCHEMA_VERSION,
            "benchmark_version": BENCHMARK_VERSION,
            "task_id": self.task_id,
            "split": self.split,
            "capability_id": self.capability_id,
            "secondary_capabilities": list(self.secondary_capabilities),
            "difficulty": self.difficulty,
            "language": self.language,
            "horizon_tier": self.horizon_tier,
            "user_request": self.user_request,
            "environment_id": self.environment_id,
            "available_tools": list(self.available_tools),
            "hard_constraints": list(self.hard_constraints),
            "budget_tier": self.budget_tier,
            "budget": self.budget,
            "metadata": dict(self.metadata),
        }
        _assert_no_forbidden_fields(value)
        return value


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from error
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row must be an object at {path}:{line_number}")
            rows.append(value)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
