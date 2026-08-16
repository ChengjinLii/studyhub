"""Strict trajectory dataset contract for Router RL maturity v2."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from ..spec import ALLOWED_TOOLS, canonical_json

MATURITY_SCHEMA_VERSION = "studyhub.agent.router_rl.trajectory_state.v2"
MATURITY_SPLITS = frozenset({"train", "validation", "test", "sealed"})
FORBIDDEN_PROVENANCE_MARKERS = (
    "router_grpo_pilot_v1/test",
    "router_teacher_hidden",
    "router_final_holdout",
    "production_database",
    "production_api",
    "paid_material",
)


class MaturityDatasetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MaturityRewardRubric:
    expected_mode: str
    expected_tools: tuple[str, ...]
    query_terms: tuple[str, ...]
    prior_queries: tuple[str, ...]
    trusted_material_ids: tuple[int, ...]
    explicit_pages: tuple[int, ...]
    answer_terms: tuple[str, ...]
    must_refuse: bool
    evidence_required: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MaturityRewardRubric:
        expected_mode = _string(value.get("expected_mode"), "expected_mode")
        if expected_mode not in {"tools", "final"}:
            raise MaturityDatasetError("expected_mode must be tools or final")
        expected_tools = tuple(_string_list(value.get("expected_tools", []), "expected_tools"))
        if expected_mode == "tools" and len(expected_tools) != 1:
            raise MaturityDatasetError("tool states must identify exactly one oracle tool")
        if expected_mode == "final" and expected_tools:
            raise MaturityDatasetError("final states cannot identify an oracle tool")
        if any(tool not in ALLOWED_TOOLS for tool in expected_tools):
            raise MaturityDatasetError("rubric contains a non-readonly tool")
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
class MaturityRouterState:
    state_id: str
    episode_id: str
    split: str
    template_id: str
    family: str
    step_index: int
    max_steps: int
    request_payload: dict[str, Any]
    rubric: MaturityRewardRubric
    oracle_output: dict[str, Any]
    source_material_ids: tuple[int, ...]
    next_state_id: str | None
    terminal: bool
    training_eligible: bool
    training_export_allowed: bool
    messages: tuple[dict[str, str], ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MaturityRouterState:
        if value.get("schema_version") != MATURITY_SCHEMA_VERSION:
            raise MaturityDatasetError("unsupported maturity state schema")
        state_id = _string(value.get("state_id"), "state_id")
        episode_id = _string(value.get("episode_id"), "episode_id")
        split = _string(value.get("split"), "split")
        if split not in MATURITY_SPLITS:
            raise MaturityDatasetError(f"unsupported maturity split: {split}")
        step_index = _nonnegative_int(value.get("step_index"), "step_index")
        max_steps = _positive_int(value.get("max_steps"), "max_steps")
        if step_index >= max_steps:
            raise MaturityDatasetError("step_index must be below max_steps")
        terminal = value.get("terminal") is True
        next_value = value.get("next_state_id")
        next_state_id = _string(next_value, "next_state_id") if next_value is not None else None
        if terminal == (next_state_id is not None):
            raise MaturityDatasetError("terminal and next_state_id are inconsistent")
        request_payload = _mapping(value.get("request_payload"), "request_payload")
        _validate_request_payload(request_payload)
        messages = tuple(_validate_messages(value.get("messages"), request_payload))
        rubric = MaturityRewardRubric.from_mapping(_mapping(value.get("reward_rubric"), "reward_rubric"))
        oracle_output = _mapping(value.get("oracle_output"), "oracle_output")
        _validate_oracle_output(oracle_output, rubric)
        training_eligible = value.get("training_eligible") is True
        training_export_allowed = value.get("training_export_allowed") is True
        if training_export_allowed and (split != "train" or not training_eligible):
            raise MaturityDatasetError("only eligible train states may be exported")
        if split != "train" and (training_eligible or training_export_allowed):
            raise MaturityDatasetError("evaluation and sealed states must never be training eligible")
        isolation = _mapping(value.get("isolation"), "isolation")
        required_false = (
            "production_api_called",
            "production_database_accessed",
            "production_oss_write_called",
            "paid_material_used",
            "legacy_v1_test_used",
            "production_final_holdout_read",
        )
        if any(isolation.get(name) is not False for name in required_false):
            raise MaturityDatasetError("maturity state violates the isolation contract")
        provenance = canonical_json(value.get("provenance", {})).casefold()
        if any(marker in provenance for marker in FORBIDDEN_PROVENANCE_MARKERS):
            raise MaturityDatasetError("maturity state provenance references a forbidden source")
        return cls(
            state_id=state_id,
            episode_id=episode_id,
            split=split,
            template_id=_string(value.get("template_id"), "template_id"),
            family=_string(value.get("family"), "family"),
            step_index=step_index,
            max_steps=max_steps,
            request_payload=request_payload,
            rubric=rubric,
            oracle_output=oracle_output,
            source_material_ids=tuple(_positive_int_list(value.get("source_material_ids", []), "source_material_ids")),
            next_state_id=next_state_id,
            terminal=terminal,
            training_eligible=training_eligible,
            training_export_allowed=training_export_allowed,
            messages=messages,
        )


def load_maturity_states(
    path: str | Path,
    *,
    splits: set[str] | None = None,
    allow_sealed: bool = False,
) -> list[MaturityRouterState]:
    requested = set(splits or MATURITY_SPLITS)
    if "sealed" in requested and not allow_sealed:
        raise MaturityDatasetError("sealed split is locked; explicit authorization is required")
    unknown = requested - MATURITY_SPLITS
    if unknown:
        raise MaturityDatasetError(f"unknown requested splits: {sorted(unknown)}")
    selected: list[MaturityRouterState] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise MaturityDatasetError(f"blank JSONL line at {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MaturityDatasetError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(value, Mapping):
                raise MaturityDatasetError(f"state at line {line_number} is not an object")
            state = MaturityRouterState.from_mapping(value)
            if state.split in requested:
                selected.append(state)
    return selected


def audit_maturity_states(states: Sequence[MaturityRouterState]) -> dict[str, Any]:
    if not states:
        raise MaturityDatasetError("cannot audit an empty maturity dataset")
    errors: list[str] = []
    by_id: dict[str, MaturityRouterState] = {}
    split_counts: Counter[str] = Counter()
    split_episodes: dict[str, set[str]] = defaultdict(set)
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    material_splits: dict[int, set[str]] = defaultdict(set)
    query_splits: dict[str, set[str]] = defaultdict(set)
    prompt_splits: dict[str, set[str]] = defaultdict(set)
    template_splits: dict[str, set[str]] = defaultdict(set)
    episode_states: dict[str, list[MaturityRouterState]] = defaultdict(list)
    for state in states:
        if state.state_id in by_id:
            errors.append(f"duplicate_state_id:{state.state_id}")
        by_id[state.state_id] = state
        split_counts[state.split] += 1
        split_episodes[state.split].add(state.episode_id)
        family_counts[state.split][state.family] += 1
        episode_states[state.episode_id].append(state)
        template_splits[state.template_id].add(state.split)
        query_splits[_fingerprint(_normalize_text(state.request_payload["current_user_query"]))].add(state.split)
        prompt_splits[_fingerprint(canonical_json(state.messages))].add(state.split)
        for material_id in state.source_material_ids:
            material_splits[material_id].add(state.split)
        if state.split != "train" and state.training_export_allowed:
            errors.append(f"evaluation_export_allowed:{state.state_id}")
    for episode_id, episode in episode_states.items():
        ordered = sorted(episode, key=lambda state: state.step_index)
        if [state.step_index for state in ordered] != list(range(len(ordered))):
            errors.append(f"noncontiguous_episode:{episode_id}")
            continue
        if any(state.max_steps != len(ordered) for state in ordered):
            errors.append(f"episode_max_steps_mismatch:{episode_id}")
        if sum(state.terminal for state in ordered) != 1 or not ordered[-1].terminal:
            errors.append(f"episode_terminal_mismatch:{episode_id}")
        if len({state.split for state in ordered}) != 1:
            errors.append(f"episode_cross_split:{episode_id}")
        for current, successor in pairwise(ordered):
            if current.next_state_id != successor.state_id:
                errors.append(f"invalid_transition:{current.state_id}:{current.next_state_id}")
        if ordered[-1].next_state_id is not None:
            errors.append(f"terminal_has_successor:{ordered[-1].state_id}")
    leaks = {
        "material": _cross_split_values(material_splits),
        "normalized_query": _cross_split_values(query_splits),
        "exact_prompt": _cross_split_values(prompt_splits),
        "episode_template": _cross_split_values(template_splits),
    }
    for name, values in leaks.items():
        if values:
            errors.append(f"{name}_cross_split_leak")
    return {
        "schema_version": "studyhub.agent.router_rl.maturity_dataset_audit.v2",
        "passed": not errors,
        "states": len(states),
        "episodes": len(episode_states),
        "split_counts": dict(sorted(split_counts.items())),
        "split_episode_counts": {split: len(values) for split, values in sorted(split_episodes.items())},
        "family_counts": {split: dict(sorted(values.items())) for split, values in sorted(family_counts.items())},
        "training_export_allowed": sum(state.training_export_allowed for state in states),
        "leaks": leaks,
        "errors": sorted(set(errors)),
    }


def _validate_oracle_output(output: Mapping[str, Any], rubric: MaturityRewardRubric) -> None:
    mode = output.get("mode")
    if mode != rubric.expected_mode:
        raise MaturityDatasetError("oracle output mode differs from rubric")
    actions = output.get("actions")
    if mode == "tools":
        if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], Mapping):
            raise MaturityDatasetError("tool oracle must contain exactly one action")
        if actions[0].get("name") != rubric.expected_tools[0]:
            raise MaturityDatasetError("oracle tool differs from rubric")
        if not isinstance(actions[0].get("arguments"), Mapping):
            raise MaturityDatasetError("oracle action arguments must be an object")
    elif actions:
        raise MaturityDatasetError("final oracle cannot contain actions")


def _validate_request_payload(value: Mapping[str, Any]) -> None:
    _string(value.get("current_user_query"), "current_user_query")
    if type(value.get("force_final")) is not bool:
        raise MaturityDatasetError("force_final must be boolean")
    budget = _mapping(value.get("budget"), "budget")
    for name in ("remaining_rounds", "remaining_tool_calls", "remaining_search_calls", "remaining_candidate_slots"):
        _nonnegative_int(budget.get(name), name)
    observations = value.get("tool_observations")
    if not isinstance(observations, list):
        raise MaturityDatasetError("tool_observations must be a list")


def _validate_messages(value: object, request_payload: Mapping[str, Any]) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise MaturityDatasetError("messages must contain exactly a system and user turn")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        mapping = _mapping(item, "message")
        expected = "system" if index == 0 else "user"
        if mapping.get("role") != expected:
            raise MaturityDatasetError("message roles must be system then user")
        result.append({"role": expected, "content": _string(mapping.get("content"), "message content")})
    try:
        decoded = json.loads(result[1]["content"])
    except json.JSONDecodeError as exc:
        raise MaturityDatasetError("user message must contain strict JSON") from exc
    if canonical_json(decoded) != canonical_json(request_payload):
        raise MaturityDatasetError("user message and request payload differ")
    return result


def _cross_split_values(values: Mapping[Any, set[str]]) -> dict[str, list[str]]:
    return {str(key): sorted(splits) for key, splits in values.items() if len(splits) > 1}


def _normalize_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MaturityDatasetError(f"{name} must be an object")
    return dict(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MaturityDatasetError(f"{name} must be a nonblank string")
    return value.strip()


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MaturityDatasetError(f"{name} must be a list")
    return [_string(item, name) for item in value]


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MaturityDatasetError(f"{name} must be a positive integer")
    return value


def _positive_int_list(value: object, name: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MaturityDatasetError(f"{name} must be a list")
    return [_positive_int(item, name) for item in value]


def _nonnegative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MaturityDatasetError(f"{name} must be a nonnegative integer")
    return value
