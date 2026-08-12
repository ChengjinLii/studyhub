"""Versioned data contract for the isolated Router RL pilot."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "studyhub.agent.router_rl.state.v1"
ALLOWED_SPLITS = frozenset({"train", "validation", "test"})
ALLOWED_TOOLS = frozenset(
    {
        "search_materials",
        "inspect_materials",
        "read_pdf_evidence",
        "read_memory",
        "synthesize_course_context",
    }
)
FORBIDDEN_SOURCE_MARKERS = (
    "router_teacher_hidden",
    "router_final_holdout",
    "paid_material",
    "production_database",
)


class RouterRLSpecError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RewardRubric:
    expected_mode: str
    expected_tools: tuple[str, ...] = ()
    query_terms: tuple[str, ...] = ()
    prior_queries: tuple[str, ...] = ()
    trusted_material_ids: tuple[int, ...] = ()
    explicit_pages: tuple[int, ...] = ()
    answer_terms: tuple[str, ...] = ()
    must_refuse: bool = False
    evidence_required: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RewardRubric:
        expected_mode = _string(value.get("expected_mode"), "expected_mode")
        if expected_mode not in {"tools", "final"}:
            raise RouterRLSpecError("expected_mode must be tools or final")
        expected_tools = tuple(_string_list(value.get("expected_tools", []), "expected_tools"))
        if any(tool not in ALLOWED_TOOLS for tool in expected_tools):
            raise RouterRLSpecError("reward rubric contains a non-readonly tool")
        if expected_mode == "final" and expected_tools:
            raise RouterRLSpecError("final rubrics cannot require tools")
        if expected_mode == "tools" and not expected_tools:
            raise RouterRLSpecError("tool rubrics must name at least one tool")
        return cls(
            expected_mode=expected_mode,
            expected_tools=expected_tools,
            query_terms=tuple(_string_list(value.get("query_terms", []), "query_terms")),
            prior_queries=tuple(_string_list(value.get("prior_queries", []), "prior_queries")),
            trusted_material_ids=tuple(_positive_int_list(value.get("trusted_material_ids", []), "trusted_material_ids")),
            explicit_pages=tuple(_positive_int_list(value.get("explicit_pages", []), "explicit_pages")),
            answer_terms=tuple(_string_list(value.get("answer_terms", []), "answer_terms")),
            must_refuse=value.get("must_refuse") is True,
            evidence_required=value.get("evidence_required") is True,
        )


@dataclass(frozen=True, slots=True)
class RouterRLState:
    state_id: str
    episode_id: str
    split: str
    family: str
    step_index: int
    max_steps: int
    request_payload: dict[str, Any]
    rubric: RewardRubric
    source_material_ids: tuple[int, ...]
    next_state_id: str | None
    terminal: bool
    training_eligible: bool
    training_export_allowed: bool
    messages: tuple[dict[str, str], ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RouterRLState:
        if value.get("schema_version") != SCHEMA_VERSION:
            raise RouterRLSpecError("unsupported Router RL state schema")
        state_id = _string(value.get("state_id"), "state_id")
        episode_id = _string(value.get("episode_id"), "episode_id")
        split = _string(value.get("split"), "split")
        if split not in ALLOWED_SPLITS:
            raise RouterRLSpecError("unsupported split")
        step_index = _nonnegative_int(value.get("step_index"), "step_index")
        max_steps = _positive_int(value.get("max_steps"), "max_steps")
        if step_index >= max_steps:
            raise RouterRLSpecError("step_index must be below max_steps")
        request_payload = _mapping(value.get("request_payload"), "request_payload")
        _validate_request_payload(request_payload)
        messages = tuple(_messages(value.get("messages"), request_payload))
        source_material_ids = tuple(_positive_int_list(value.get("source_material_ids", []), "source_material_ids"))
        next_value = value.get("next_state_id")
        next_state_id = _string(next_value, "next_state_id") if next_value is not None else None
        terminal = value.get("terminal") is True
        if terminal == (next_state_id is not None):
            raise RouterRLSpecError("terminal states must omit next_state_id and non-terminal states must provide it")
        training_eligible = value.get("training_eligible") is True
        training_export_allowed = value.get("training_export_allowed") is True
        if training_export_allowed and (split != "train" or not training_eligible):
            raise RouterRLSpecError("only eligible training states may be exported")
        isolation = _mapping(value.get("isolation"), "isolation")
        if any(isolation.get(name) is not False for name in ("production_api_called", "production_database_accessed", "paid_material_used", "final_holdout_read")):
            raise RouterRLSpecError("RL state violates the offline isolation contract")
        provenance_text = canonical_json(value.get("provenance", {})).lower()
        if any(marker in provenance_text for marker in FORBIDDEN_SOURCE_MARKERS):
            raise RouterRLSpecError("RL state provenance references a forbidden source")
        return cls(
            state_id=state_id,
            episode_id=episode_id,
            split=split,
            family=_string(value.get("family"), "family"),
            step_index=step_index,
            max_steps=max_steps,
            request_payload=request_payload,
            rubric=RewardRubric.from_mapping(_mapping(value.get("reward_rubric"), "reward_rubric")),
            source_material_ids=source_material_ids,
            next_state_id=next_state_id,
            terminal=terminal,
            training_eligible=training_eligible,
            training_export_allowed=training_export_allowed,
            messages=messages,
        )


def load_states(path: str | Path, *, splits: set[str] | None = None) -> list[RouterRLState]:
    selected: list[RouterRLState] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise RouterRLSpecError(f"blank JSONL line at {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RouterRLSpecError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(value, Mapping):
                raise RouterRLSpecError(f"state at line {line_number} is not an object")
            state = RouterRLState.from_mapping(value)
            if splits is None or state.split in splits:
                selected.append(state)
    return selected


def audit_states(states: Sequence[RouterRLState]) -> dict[str, Any]:
    ids: set[str] = set()
    by_id = {state.state_id: state for state in states}
    errors: list[str] = []
    split_counts: Counter[str] = Counter()
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    material_splits: dict[int, set[str]] = defaultdict(set)
    episode_steps: dict[str, list[int]] = defaultdict(list)
    for state in states:
        if state.state_id in ids:
            errors.append(f"duplicate_state_id:{state.state_id}")
        ids.add(state.state_id)
        split_counts[state.split] += 1
        family_counts[state.split][state.family] += 1
        episode_steps[state.episode_id].append(state.step_index)
        for material_id in state.source_material_ids:
            material_splits[material_id].add(state.split)
        if state.next_state_id is not None:
            successor = by_id.get(state.next_state_id)
            if successor is None:
                errors.append(f"missing_next_state:{state.state_id}:{state.next_state_id}")
            elif successor.episode_id != state.episode_id or successor.step_index != state.step_index + 1:
                errors.append(f"invalid_transition:{state.state_id}:{state.next_state_id}")
    for episode_id, steps in episode_steps.items():
        if sorted(steps) != list(range(len(steps))):
            errors.append(f"noncontiguous_episode:{episode_id}")
    leaks = {str(key): sorted(value) for key, value in material_splits.items() if len(value) > 1}
    if leaks:
        errors.append("material_split_leak")
    return {
        "schema_version": "studyhub.agent.router_rl.dataset_audit.v1",
        "passed": not errors,
        "states": len(states),
        "episodes": len(episode_steps),
        "split_counts": dict(sorted(split_counts.items())),
        "family_counts": {split: dict(sorted(counts.items())) for split, counts in sorted(family_counts.items())},
        "training_export_allowed": sum(state.training_export_allowed for state in states),
        "material_split_leaks": leaks,
        "errors": errors,
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_request_payload(value: Mapping[str, Any]) -> None:
    _string(value.get("current_user_query"), "current_user_query")
    budget = _mapping(value.get("budget"), "budget")
    for name in ("remaining_rounds", "remaining_tool_calls", "remaining_search_calls", "remaining_candidate_slots"):
        _nonnegative_int(budget.get(name), name)
    if type(value.get("force_final")) is not bool:
        raise RouterRLSpecError("force_final must be boolean")
    observations = value.get("tool_observations")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise RouterRLSpecError("tool_observations must be a list")


def _messages(value: object, request_payload: Mapping[str, Any]) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise RouterRLSpecError("messages must contain system and user turns")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        message = _mapping(item, "message")
        expected_role = "system" if index == 0 else "user"
        if message.get("role") != expected_role:
            raise RouterRLSpecError("message roles must be system then user")
        result.append({"role": expected_role, "content": _string(message.get("content"), "message content")})
    try:
        decoded = json.loads(result[1]["content"])
    except json.JSONDecodeError as exc:
        raise RouterRLSpecError("user message must contain strict JSON") from exc
    if canonical_json(decoded) != canonical_json(request_payload):
        raise RouterRLSpecError("user message and request_payload differ")
    return result


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RouterRLSpecError(f"{name} must be an object")
    return dict(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RouterRLSpecError(f"{name} must be a nonblank string")
    return value.strip()


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RouterRLSpecError(f"{name} must be a list")
    return [_string(item, name) for item in value]


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RouterRLSpecError(f"{name} must be a positive integer")
    return value


def _positive_int_list(value: object, name: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RouterRLSpecError(f"{name} must be a list")
    return [_positive_int(item, name) for item in value]


def _nonnegative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RouterRLSpecError(f"{name} must be a non-negative integer")
    return value
