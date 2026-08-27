from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BENCHMARK_VERSION = "studyhub-agentbench-v2"
TASK_SCHEMA_VERSION = "studyhub.agentbench-task.v2"
ENVIRONMENT_SCHEMA_VERSION = "studyhub.agentbench-environment.v2"
GRADER_SCHEMA_VERSION = "studyhub.agentbench-grader.v2"

SPLITS = frozenset({"regression", "development", "sealed_a", "sealed_b", "calibration_challenge"})
DIFFICULTIES = frozenset({"UNSCORED", "easy", "medium", "hard", "extreme"})
ENVIRONMENT_ORIGINS = frozenset(
    {
        "authentic_studyhub_preview",
        "authentic_web_snapshot",
        "synthetic_adversarial",
        "synthetic_memory",
        "synthetic_state",
    }
)
PUBLIC_FORBIDDEN_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "acceptable_semantic_answers",
        "contradiction_patterns",
        "expected_answer",
        "expected_answers",
        "expected_call",
        "expected_calls",
        "gold_query",
        "gold_source_order",
        "gold_trajectory",
        "oracle_answer",
        "reference_actions",
        "rubric",
        "support_facts",
        "support_spans",
        "supporting_facts",
        "verifier",
        "grader",
    }
)

BUDGETS: dict[str, dict[str, int]] = {
    "direct": {"max_model_turns": 3, "max_tool_calls": 1, "max_context_tokens": 4096},
    "short": {"max_model_turns": 6, "max_tool_calls": 4, "max_context_tokens": 8192},
    "extended": {"max_model_turns": 12, "max_tool_calls": 10, "max_context_tokens": 16384},
    "research": {"max_model_turns": 20, "max_tool_calls": 18, "max_context_tokens": 32768},
}


def assert_no_public_oracle(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        forbidden = PUBLIC_FORBIDDEN_FIELDS & set(value)
        if forbidden:
            raise ValueError(f"public task exposes oracle fields at {path}: {sorted(forbidden)}")
        for key, nested in value.items():
            assert_no_public_oracle(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            assert_no_public_oracle(nested, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class BenchmarkTaskV2:
    task_id: str
    split: str
    capability_id: str
    secondary_capabilities: tuple[str, ...]
    difficulty: str
    language: str
    user_request: str
    environment_id: str
    available_tools: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    budget_tier: str
    source_group_id: str
    semantic_template_cluster: str
    environment_origin: str
    difficulty_features: dict[str, int | str]
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BenchmarkTaskV2:
        assert_no_public_oracle(value)
        if value.get("schema_version") != TASK_SCHEMA_VERSION:
            raise ValueError(f"unsupported task schema: {value.get('schema_version')}")
        if value.get("benchmark_version") != BENCHMARK_VERSION:
            raise ValueError(f"unsupported benchmark version: {value.get('benchmark_version')}")
        task = cls(
            task_id=str(value["task_id"]),
            split=str(value["split"]),
            capability_id=str(value["capability_id"]),
            secondary_capabilities=tuple(map(str, value.get("secondary_capabilities", []))),
            difficulty=str(value["difficulty"]),
            language=str(value["language"]),
            user_request=str(value["user_request"]),
            environment_id=str(value["environment_id"]),
            available_tools=tuple(map(str, value.get("available_tools", []))),
            hard_constraints=tuple(map(str, value.get("hard_constraints", []))),
            budget_tier=str(value["budget_tier"]),
            source_group_id=str(value["source_group_id"]),
            semantic_template_cluster=str(value["semantic_template_cluster"]),
            environment_origin=str(value["environment_origin"]),
            difficulty_features=dict(value.get("difficulty_features", {})),
            metadata=dict(value.get("metadata", {})),
        )
        task.validate()
        return task

    def validate(self) -> None:
        if not self.task_id or self.task_id != self.environment_id:
            raise ValueError("task_id and environment_id must be identical and non-empty")
        if self.split not in SPLITS:
            raise ValueError(f"invalid split: {self.split}")
        if self.difficulty not in DIFFICULTIES:
            raise ValueError(f"invalid difficulty: {self.difficulty}")
        if self.language not in {"zh", "en"}:
            raise ValueError(f"invalid language: {self.language}")
        if self.budget_tier not in BUDGETS:
            raise ValueError(f"invalid budget tier: {self.budget_tier}")
        if self.environment_origin not in ENVIRONMENT_ORIGINS:
            raise ValueError(f"invalid environment origin: {self.environment_origin}")
        if len(self.user_request.strip()) < 12:
            raise ValueError("user_request is too short")
        if not self.source_group_id or not self.semantic_template_cluster:
            raise ValueError("source and semantic-template clusters are required")
        if len(self.available_tools) != len(set(self.available_tools)):
            raise ValueError("available_tools contains duplicates")
        required_features = {
            "min_required_evidence_count",
            "candidate_source_count",
            "retrieval_depth",
            "tool_family_count",
            "state_transition_count",
            "conflict_count",
            "expected_horizon_band",
            "distractor_count",
            "ambiguity_level",
        }
        missing = required_features - set(self.difficulty_features)
        if missing:
            raise ValueError(f"difficulty features missing: {sorted(missing)}")

    @property
    def budget(self) -> dict[str, int]:
        return dict(BUDGETS[self.budget_tier])

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
            "user_request": self.user_request,
            "environment_id": self.environment_id,
            "available_tools": list(self.available_tools),
            "hard_constraints": list(self.hard_constraints),
            "budget_tier": self.budget_tier,
            "budget": self.budget,
            "source_group_id": self.source_group_id,
            "semantic_template_cluster": self.semantic_template_cluster,
            "environment_origin": self.environment_origin,
            "difficulty_features": dict(self.difficulty_features),
            "metadata": dict(self.metadata),
        }
        assert_no_public_oracle(value)
        return value


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from error
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row must be an object at {path}:{line_number}")
            rows.append(row)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
