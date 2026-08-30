from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

_TOOL_MARKUP = re.compile(r"<tool_call>|<function=|\"tool_calls?\"", re.IGNORECASE)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_rank(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProtocolItem:
    item_id: str
    row_id: str
    source_dataset: str
    source_family: str
    quality_tier: str
    turn_index: int
    expected_kind: str
    expected_tool_names: tuple[str, ...]
    observation_conditioned: bool
    prefix_messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]


def _target_kind(message: dict[str, Any], *, final_message: bool) -> str:
    if message.get("tool_calls"):
        return "tool_call"
    if str(message.get("content", "")).strip():
        return "final" if final_message else "continuation"
    raise ValueError("assistant target has neither tool calls nor visible content")


def build_protocol_items(rows: Iterable[dict[str, Any]]) -> list[ProtocolItem]:
    items: list[ProtocolItem] = []
    row_ids: set[str] = set()
    for row in rows:
        if row.get("split") != "protocol_holdout":
            raise ValueError(f"non-protocol row supplied: {row.get('id')}")
        row_id = str(row.get("id", ""))
        if not row_id or row_id in row_ids:
            raise ValueError(f"missing or duplicate protocol row id: {row_id}")
        row_ids.add(row_id)
        messages = row.get("messages")
        tools = row.get("tools")
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"protocol row has no messages: {row_id}")
        if not isinstance(tools, list):
            raise ValueError(f"protocol row has no tool list: {row_id}")
        assistant_indices = [index for index, message in enumerate(messages) if message.get("role") == "assistant"]
        if not assistant_indices:
            raise ValueError(f"protocol row has no assistant target: {row_id}")
        final_assistant_index = assistant_indices[-1]
        for ordinal, message_index in enumerate(assistant_indices):
            message = messages[message_index]
            kind = _target_kind(message, final_message=message_index == final_assistant_index)
            calls = message.get("tool_calls") or []
            names = tuple(str(call.get("function", {}).get("name", "")) for call in calls)
            if any(not name for name in names):
                raise ValueError(f"protocol row has unnamed target tool: {row_id}:{message_index}")
            prefix = tuple(dict(value) for value in messages[:message_index])
            items.append(
                ProtocolItem(
                    item_id=f"{row_id}:assistant:{ordinal}",
                    row_id=row_id,
                    source_dataset=str(row.get("source_dataset", "unknown")),
                    source_family=str(row.get("source_family", "unknown")),
                    quality_tier=str(row.get("quality_tier", "unknown")),
                    turn_index=ordinal,
                    expected_kind=kind,
                    expected_tool_names=names,
                    observation_conditioned=bool(prefix and prefix[-1].get("role") == "tool"),
                    prefix_messages=prefix,
                    tools=tuple(dict(value) for value in tools),
                )
            )
    return items


def select_protocol_rows(rows: list[dict[str, Any]], *, max_rows: int, seed: int) -> list[dict[str, Any]]:
    if max_rows < 0:
        raise ValueError("max_rows must be non-negative")
    selected = [row for row in rows if row.get("split") == "protocol_holdout"]
    selected.sort(key=lambda row: stable_rank(seed, str(row.get("id", ""))))
    return selected[:max_rows] if max_rows else selected


def wire_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for source in messages:
        message = dict(source)
        calls = []
        for source_call in message.get("tool_calls") or []:
            call = dict(source_call)
            function = dict(call.get("function") or {})
            arguments = function.get("arguments", {})
            if not isinstance(arguments, str):
                arguments = canonical_json(arguments)
            function["arguments"] = arguments
            call["function"] = function
            calls.append(call)
        if calls:
            message["tool_calls"] = calls
        normalized.append(message)
    return normalized


def _message_from_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}, "missing_choices"
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        return {}, "missing_message"
    return dict(choice["message"]), None


def classify_chat_completion(payload: dict[str, Any], *, allowed_tool_names: set[str]) -> dict[str, Any]:
    message, error = _message_from_payload(payload)
    if error:
        return {
            "response_kind": "invalid",
            "protocol_valid": False,
            "provider_payload_error": error,
            "visible_nonempty": False,
            "reasoning_tool_markup": False,
            "same_turn_text_and_tool": False,
            "tool_names": [],
            "unknown_tool_names": [],
            "invalid_argument_calls": 0,
        }

    content = str(message.get("content") or "").strip()
    reasoning = "\n".join(
        str(message.get(key) or "")
        for key in ("reasoning", "reasoning_content")
        if message.get(key)
    )
    raw_calls = message.get("tool_calls") or []
    tool_names: list[str] = []
    invalid_arguments = 0
    malformed_calls = 0
    for call in raw_calls:
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            malformed_calls += 1
            continue
        function = call["function"]
        name = str(function.get("name", ""))
        if not name:
            malformed_calls += 1
            continue
        tool_names.append(name)
        arguments = function.get("arguments", "")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                invalid_arguments += 1
                continue
        if not isinstance(arguments, dict):
            invalid_arguments += 1

    has_tools = bool(raw_calls)
    same_turn = bool(content and has_tools)
    if same_turn:
        response_kind = "mixed"
    elif has_tools:
        response_kind = "tool_call"
    elif content:
        response_kind = "text"
    else:
        response_kind = "empty"
    unknown = sorted(name for name in tool_names if name not in allowed_tool_names)
    reasoning_tool_markup = bool(_TOOL_MARKUP.search(reasoning))
    protocol_valid = bool(
        response_kind == "tool_call"
        and tool_names
        and not malformed_calls
        and not invalid_arguments
        and not unknown
        and not reasoning_tool_markup
    )
    return {
        "response_kind": response_kind,
        "protocol_valid": protocol_valid,
        "provider_payload_error": None,
        "visible_nonempty": bool(content),
        "reasoning_tool_markup": reasoning_tool_markup,
        "same_turn_text_and_tool": same_turn,
        "tool_names": tool_names,
        "unknown_tool_names": unknown,
        "invalid_argument_calls": invalid_arguments,
        "malformed_tool_calls": malformed_calls,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "content_length": len(content),
        "reasoning_sha256": hashlib.sha256(reasoning.encode()).hexdigest() if reasoning else None,
        "reasoning_length": len(reasoning),
    }


def score_protocol_item(item: ProtocolItem, response: dict[str, Any]) -> dict[str, Any]:
    expected_names = Counter(item.expected_tool_names)
    actual_names = Counter(map(str, response.get("tool_names", [])))
    if item.expected_kind == "tool_call":
        target_pass = bool(response.get("protocol_valid"))
    else:
        target_pass = bool(
            response.get("response_kind") == "text"
            and response.get("visible_nonempty")
            and not response.get("same_turn_text_and_tool")
        )
    return {
        "item_id": item.item_id,
        "row_id": item.row_id,
        "source_dataset": item.source_dataset,
        "source_family": item.source_family,
        "quality_tier": item.quality_tier,
        "turn_index": item.turn_index,
        "expected_kind": item.expected_kind,
        "expected_tool_names": list(item.expected_tool_names),
        "observation_conditioned": item.observation_conditioned,
        "target_pass": target_pass,
        "exact_tool_name_match": expected_names == actual_names if item.expected_kind == "tool_call" else None,
        "response": response,
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 8) if denominator else 1.0


def _slice_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = Counter(str(row["expected_kind"]) for row in rows)
    passed = Counter(str(row["expected_kind"]) for row in rows if row.get("target_pass"))
    return {
        "items": len(rows),
        "expected": dict(sorted(expected.items())),
        "target_pass_rate": _rate(sum(passed.values()), len(rows)),
        "tool_call_parse_rate": _rate(passed["tool_call"], expected["tool_call"]),
        "continuation_nonempty_rate": _rate(passed["continuation"], expected["continuation"]),
        "final_nonempty_rate": _rate(passed["final"], expected["final"]),
    }


def summarize_protocol_results(
    rows: list[dict[str, Any]],
    *,
    expected_items: int,
    expected_rows: int,
    tool_call_parse_minimum: float,
    final_nonempty_minimum: float,
    observation_mask_pass: bool,
) -> dict[str, Any]:
    scored = [row for row in rows if row.get("status") == "SCORED"]
    infra = [row for row in rows if row.get("status") != "SCORED"]
    core = _slice_metrics(scored)
    seen_rows = {str(row.get("row_id")) for row in scored}
    complete = len(scored) == expected_items and len(seen_rows) == expected_rows and not infra
    gates = {
        "all_items_scored": complete,
        "tool_call_parse_rate": core["tool_call_parse_rate"] >= tool_call_parse_minimum,
        "final_nonempty_rate": core["final_nonempty_rate"] >= final_nonempty_minimum,
        "observation_mask_audit": observation_mask_pass,
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        grouped[str(row.get("source_family", "unknown"))].append(row)
    if not complete:
        status = "INCOMPLETE_PROTOCOL_HOLDOUT_INFRA"
    elif all(gates.values()):
        status = "PASS_SFT1_PROTOCOL_HOLDOUT"
    else:
        status = "FAIL_SFT1_PROTOCOL_HOLDOUT"
    return {
        "schema_version": "studyhub.sft1-protocol-holdout-result.v1",
        "status": status,
        "claim_boundary": "TEACHER_FORCED_PROTOCOL_VALIDITY_ONLY_NOT_AGENT_CAPABILITY",
        "expected_rows": expected_rows,
        "expected_items": expected_items,
        "scored_items": len(scored),
        "infra_items": len(infra),
        "metrics": {
            **core,
            "reasoning_tool_markup_rate": _rate(
                sum(bool(row.get("response", {}).get("reasoning_tool_markup")) for row in scored),
                len(scored),
            ),
            "same_turn_text_and_tool_rate": _rate(
                sum(bool(row.get("response", {}).get("same_turn_text_and_tool")) for row in scored),
                len(scored),
            ),
            "exact_tool_name_match_rate": _rate(
                sum(row.get("exact_tool_name_match") is True for row in scored),
                sum(row.get("expected_kind") == "tool_call" for row in scored),
            ),
            "observation_conditioned_target_pass_rate": _rate(
                sum(bool(row.get("target_pass")) for row in scored if row.get("observation_conditioned")),
                sum(bool(row.get("observation_conditioned")) for row in scored),
            ),
            "reasoning_tool_markup_on_expected_tool_rate": _rate(
                sum(
                    bool(row.get("response", {}).get("reasoning_tool_markup"))
                    for row in scored
                    if row.get("expected_kind") == "tool_call"
                ),
                sum(row.get("expected_kind") == "tool_call" for row in scored),
            ),
        },
        "thresholds": {
            "tool_call_parse_minimum": tool_call_parse_minimum,
            "final_nonempty_minimum": final_nonempty_minimum,
        },
        "gates": gates,
        "source_family_slices": {
            family: _slice_metrics(values) for family, values in sorted(grouped.items())
        },
    }


def item_manifest(item: ProtocolItem) -> dict[str, Any]:
    value = asdict(item)
    value["prefix_sha256"] = hashlib.sha256(canonical_json(value.pop("prefix_messages")).encode()).hexdigest()
    value["tools_sha256"] = hashlib.sha256(canonical_json(value.pop("tools")).encode()).hexdigest()
    return value
