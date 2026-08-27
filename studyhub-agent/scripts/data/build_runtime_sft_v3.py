#!/usr/bin/env python3
"""Build the auditable v3 SFT candidate pool in the Hermes policy space."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from studyhub_agent.trajectory.runtime_sft import (
    assistant_tool_call,
    make_record,
    normalize_legacy_conversation,
    openai_tools,
    stable_hash,
    tool_observation,
    validate_runtime_trajectory,
)

TRANSFORM_VERSION = "runtime-native-sft-v3.0"
DEFAULT_POOL_LIMITS = {
    "toolace": 9_000,
    "hermes_function_calling": 3_100,
    "coig_exam": 20_000,
    "studyhub_2wiki_replay": 30_000,
    "studyhub_qasper_replay": 3_590,
    "studyhub_metadata_replay": 12_000,
    "studyhub_memory_replay": 8_000,
    "studyhub_acl_recovery": 8_000,
    "studyhub_web_fallback": 6_000,
    "studyhub_state_tools": 6_000,
}

_SPACE = re.compile(r"\s+")
_TOOLACE_CALL = re.compile(r"^\[(.*)]$", re.DOTALL)


def clean(value: Any, *, limit: int | None = None) -> str:
    text = _SPACE.sub(" ", str(value or "").replace("\x00", " ")).strip()
    return text if limit is None else text[:limit]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def benchmark_lock(manifest_path: Path, inventory_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("benchmark_version") != "studyhub-agentbench-v2":
        raise RuntimeError("runtime SFT must be isolated from StudyHub AgentBench v2")
    if manifest.get("benchmark_revision") != "2.0.0":
        raise RuntimeError(f"unexpected benchmark revision: {manifest.get('benchmark_revision')}")
    if manifest.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("benchmark manifest is not frozen")
    expected_inventory_hash = manifest.get("hidden_files", {}).get("source-inventory.jsonl")
    actual_inventory_hash = sha256(inventory_path)
    if not expected_inventory_hash or actual_inventory_hash != expected_inventory_hash:
        raise RuntimeError("benchmark source inventory does not match the frozen manifest")
    task_count = sum(int(value) for value in manifest.get("counts", {}).values())
    if task_count != 98:
        raise RuntimeError(f"unexpected frozen benchmark task count: {task_count}")
    return {
        "benchmark_version": manifest["benchmark_version"],
        "benchmark_revision": manifest["benchmark_revision"],
        "benchmark_status": manifest["status"],
        "benchmark_tasks": task_count,
        "benchmark_manifest_sha256": sha256(manifest_path),
        "benchmark_source_inventory_sha256": actual_inventory_hash,
    }


def provenance(source: Mapping[str, Any], *, raw_files: Iterable[Path]) -> dict[str, Any]:
    return {
        "revision": source.get("revision"),
        "license": source.get("license"),
        "source_url": source.get("source_url"),
        "attribution": source.get("attribution"),
        "raw_files": [{"path": str(path), "sha256": sha256(path)} for path in raw_files],
        "transform_version": TRANSFORM_VERSION,
    }


def selected_by_hash(rows: Iterable[Any], limit: int, key) -> list[Any]:
    heap: list[tuple[int, int, Any]] = []
    for ordinal, row in enumerate(rows):
        rank = int(stable_hash(str(key(row)), salt="v3-candidate-rank")[:16], 16)
        item = (-rank, ordinal, row)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    return [row for _rank, _ordinal, row in sorted(heap, key=lambda item: (-item[0], item[1]))]


def _last_assistant_is_final(messages: list[dict[str, Any]]) -> bool:
    return bool(
        messages
        and messages[-1].get("role") == "assistant"
        and not messages[-1].get("tool_calls")
        and clean(messages[-1].get("content"))
    )


def _split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote:
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    if value[start:].strip():
        parts.append(value[start:].strip())
    return parts


def _split_toolace_expressions(value: str, aliases: Mapping[str, str]) -> list[str]:
    expressions: list[str] = []
    offset = 0
    folded = value.casefold()
    ordered_aliases = sorted(aliases, key=len, reverse=True)
    while offset < len(value):
        while offset < len(value) and (value[offset].isspace() or value[offset] == ","):
            offset += 1
        if offset >= len(value):
            break
        raw_name = next(
            (candidate for candidate in ordered_aliases if folded.startswith(candidate + "(", offset)),
            None,
        )
        if raw_name is None:
            return []
        open_parenthesis = offset + len(raw_name)
        depth = 0
        quote = ""
        escaped = False
        end = -1
        for index in range(open_parenthesis, len(value)):
            character = value[index]
            if escaped:
                escaped = False
                continue
            if character == "\\" and quote:
                escaped = True
                continue
            if quote:
                if character == quote:
                    quote = ""
                continue
            if character in {'"', "'"}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end < 0:
            return []
        expressions.append(value[offset:end].strip())
        offset = end
    return expressions


def _safe_tool_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return name[:64] or "unnamed_tool"


def _normalize_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {key: _normalize_json_schema(item) for key, item in value.items() if item is not None}
    if normalized.get("type") == "dict":
        normalized["type"] = "object"
    if normalized.get("type") == "list":
        normalized["type"] = "array"
    normalized.setdefault("additionalProperties", False) if normalized.get("type") == "object" else None
    return normalized


def _toolace_tools(system: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    marker = "Here is a list of functions in JSON format that you can invoke:"
    if marker not in system:
        return [], {}
    tail = system.split(marker, 1)[1].lstrip()
    try:
        payload, _end = json.JSONDecoder().raw_decode(tail)
    except json.JSONDecodeError:
        return [], {}
    tools = []
    aliases = {}
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        raw_name = str(row["name"])
        name = _safe_tool_name(raw_name)
        aliases[raw_name.casefold()] = name
        parameters = _normalize_json_schema(row.get("parameters") or {"type": "object", "properties": {}})
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": clean(row.get("description")),
                    "parameters": parameters,
                },
            }
        )
    return tools, aliases


def _toolace_calls(value: str, aliases: Mapping[str, str]) -> list[tuple[str, dict[str, Any]]]:
    match = _TOOLACE_CALL.fullmatch(value.strip())
    if not match:
        return []
    calls = []
    for expression in _split_toolace_expressions(match.group(1), aliases):
        raw_name = next(
            (
                candidate
                for candidate in sorted(aliases, key=len, reverse=True)
                if expression.casefold().startswith(candidate + "(") and expression.endswith(")")
            ),
            None,
        )
        if raw_name is None:
            return []
        name = aliases.get(raw_name.casefold())
        if not name:
            return []
        arguments: dict[str, Any] = {}
        argument_text = expression[len(raw_name) + 1 : -1]
        for parameter in _split_top_level(argument_text):
            if "=" not in parameter:
                return []
            key, raw_value = parameter.split("=", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            if not key:
                return []
            try:
                parsed_value = json.loads(raw_value)
            except json.JSONDecodeError:
                if (raw_value.startswith("'") and raw_value.endswith("'")) or (
                    raw_value.startswith('"') and raw_value.endswith('"')
                ):
                    parsed_value = raw_value[1:-1]
                else:
                    parsed_value = raw_value
            arguments[key] = parsed_value
        calls.append((name, arguments))
    return calls


def _toolace_observations(
    content: str,
    pending: list[tuple[str, dict[str, Any], str]],
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = content
    rows = payload if isinstance(payload, list) else [payload]
    observations: list[dict[str, Any]] = []
    for index, (name, arguments, call_id) in enumerate(pending):
        recorded = rows[index] if index < len(rows) else None
        observations.append(
            tool_observation(
                name,
                {
                    "ok": True,
                    "tool": name,
                    "arguments": arguments,
                    "result": recorded,
                    "fixture_origin": "toolace_recorded_observation",
                },
                call_id=call_id,
            )
        )
    return observations


def _normalize_toolace(row: Mapping[str, Any], *, index: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tools, aliases = _toolace_tools(str(row.get("system", "")))
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are StudyHub Agent. Use the available functions when required, "
                "then explain the completed result to the user."
            ),
        }
    ]
    pending: list[tuple[str, dict[str, Any], str]] = []
    call_index = 0
    last_complete_length = 0
    for item in row.get("conversations", []):
        role = str(item.get("from", ""))
        content = clean(item.get("value"))
        if role == "user" and content:
            if pending:
                if not last_complete_length:
                    return [], []
                messages = messages[:last_complete_length]
                pending.clear()
            messages.append({"role": "user", "content": content})
            continue
        if role == "tool" and content:
            if not pending:
                return [], []
            messages.extend(_toolace_observations(content, pending))
            pending.clear()
            continue
        if role != "assistant" or not content:
            continue
        calls = _toolace_calls(content, aliases)
        if calls:
            if pending:
                return [], []
            normalized_calls = []
            for name, arguments in calls:
                call_id = f"call_{stable_hash(f'toolace:{index}:{call_index}:{name}')[:20]}"
                call_index += 1
                normalized_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                )
                pending.append((name, arguments, call_id))
            messages.append({"role": "assistant", "content": "", "tool_calls": normalized_calls})
            continue
        if pending:
            messages.extend(_toolace_observations("", pending))
            pending.clear()
        messages.append({"role": "assistant", "content": content})
        last_complete_length = len(messages)
    if _last_assistant_is_final(messages):
        return messages, tools
    if messages and messages[-1].get("role") == "assistant" and messages[-1].get("tool_calls"):
        return messages, tools
    if last_complete_length:
        return messages[:last_complete_length], tools
    return [], []


def iter_toolace(raw_root: Path, source: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    path = raw_root / "toolace/data.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    source_provenance = provenance(source, raw_files=[path])
    for index, row in enumerate(rows):
        messages, tools = _normalize_toolace(row, index=index)
        if not messages or not tools:
            continue
        complete = _last_assistant_is_final(messages) and any(message.get("role") == "tool" for message in messages)
        record = make_record(
            record_id=f"toolace:{index}",
            group_id=f"toolace:{index}",
            source_dataset="toolace",
            source_id=str(index),
            task_family="open_function_calling",
            messages=messages,
            tools=tools,
            provenance=source_provenance,
            capability_tags=["function_calling", "tool_protocol"],
            trajectory_status="complete" if complete else "action_only",
            quality_tier="expert_action_synthetic_observation" if complete else "expert_action_only",
        )
        if complete:
            if not validate_runtime_trajectory(record):
                yield record
        elif any(message.get("role") == "assistant" and message.get("tool_calls") for message in messages):
            if not validate_runtime_trajectory(record):
                yield record


def iter_hermes(raw_root: Path, source: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    root = raw_root / "hermes_function_calling"
    role_map = {"system": "system", "human": "user", "gpt": "assistant", "tool": "tool"}
    function_path = root / "func-calling.json"
    source_provenance = provenance(
        source,
        raw_files=[function_path, root / "json-mode-agentic.json"],
    )
    for index, row in enumerate(json.loads(function_path.read_text(encoding="utf-8"))):
        messages, tools = normalize_legacy_conversation(
            row.get("conversations", []),
            role_map=role_map,
            id_salt=f"hermes-fc:{row.get('id', index)}",
        )
        if not messages or not tools:
            continue
        complete = _last_assistant_is_final(messages) and any(message.get("role") == "tool" for message in messages)
        record = make_record(
            record_id=f"hermes-fc:{row.get('id', index)}",
            group_id=f"hermes:{row.get('id', index)}",
            source_dataset="hermes_function_calling",
            source_id=f"func-calling:{row.get('id', index)}",
            task_family="open_function_calling",
            messages=messages,
            tools=tools,
            provenance=source_provenance,
            capability_tags=["function_calling", "tool_protocol"],
            trajectory_status="complete" if complete else "action_only",
            quality_tier="expert_complete" if complete else "expert_action_only",
        )
        if not validate_runtime_trajectory(record):
            yield record
    json_path = root / "json-mode-agentic.json"
    for index, row in enumerate(json.loads(json_path.read_text(encoding="utf-8"))):
        messages = [
            {"role": role_map[item["from"]], "content": clean(item.get("value"))}
            for item in row.get("conversations", [])
            if item.get("from") in role_map and clean(item.get("value"))
        ]
        if not _last_assistant_is_final(messages):
            continue
        record = make_record(
            record_id=f"hermes-json:{row.get('id', index)}",
            group_id=f"hermes:{row.get('id', index)}",
            source_dataset="hermes_function_calling",
            source_id=f"json-mode:{row.get('id', index)}",
            task_family="structured_output",
            messages=messages,
            tools=[],
            provenance=source_provenance,
            capability_tags=["direct_answer", "structured_output"],
            quality_tier="expert_complete",
        )
        if not validate_runtime_trajectory(record):
            yield record


def iter_coig(raw_root: Path, source: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    path = raw_root / "coig_exam/exam_instructions.jsonl"
    source_provenance = provenance(source, raw_files=[path])
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            context = clean(row.get("textbox_q_context"), limit=7000)
            prompt = "\n\n".join(
                value
                for value in (
                    clean(row.get("textbox_q_instruction")),
                    context,
                    clean(row.get("textbox_question")),
                )
                if value
            )
            answer = clean(row.get("textbox_answer"))
            analysis = clean(row.get("textbox_answer_analysis"), limit=5000)
            if not prompt or not answer:
                continue
            response = (f"解析：{analysis}\n" if analysis else "") + f"答案：{answer}"
            messages = [
                {
                    "role": "system",
                    "content": "你是 StudyHub 学习助手。题目可直接回答时不要调用工具，并明确说明依据。",
                },
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ]
            record = make_record(
                record_id=f"coig-exam:{index}",
                group_id=f"coig-exam:{index}",
                source_dataset="coig_exam",
                source_id=str(index),
                task_family="direct_tutoring",
                messages=messages,
                tools=[],
                provenance=source_provenance,
                capability_tags=["direct_answer", "tool_abstention", "chinese_tutoring"],
                quality_tier="expert_complete",
            )
            if not validate_runtime_trajectory(record):
                yield record


def _wiki_rows(path: Path) -> Iterator[dict[str, Any]]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=1024):
        yield from batch.to_pylist()


def _source_id(prefix: str, group: str, title: str) -> str:
    return f"{prefix}:{stable_hash(f'{group}:{title}')[:16]}"


def _wiki_record(
    row: Mapping[str, Any],
    source_provenance: Mapping[str, Any],
    *,
    group_id: str,
    split: str,
) -> dict[str, Any] | None:
    row_id = str(row["_id"])
    contexts = [(str(title), list(sentences)) for title, sentences in json.loads(row["context"])]
    support = [(str(title), int(index)) for title, index in json.loads(row["supporting_facts"])]
    support_titles = list(dict.fromkeys(title for title, _index in support))[:4]
    if not support_titles:
        return None
    documents = {
        title: {
            "source_id": _source_id("wiki", row_id, title),
            "title": title,
            "text": clean(" ".join(sentences), limit=1800),
        }
        for title, sentences in contexts
    }
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are StudyHub Agent. Search before reading, use only returned evidence, "
                "and cite each factual conclusion with its source ID."
            ),
        },
        {"role": "user", "content": clean(row["question"])},
    ]
    citations = []
    for step, title in enumerate(support_titles):
        document = documents.get(title)
        if not document or not document["text"]:
            return None
        search_id = f"call_{stable_hash(f'{row_id}:search:{step}')[:20]}"
        messages.append(assistant_tool_call("knowledge_search", {"query": title, "limit": 5}, call_id=search_id))
        distractors = [value for key, value in documents.items() if key != title][:2]
        results = [document, *distractors]
        messages.append(
            tool_observation(
                "knowledge_search",
                {
                    "ok": True,
                    "query": title,
                    "results": [
                        {
                            "source_id": item["source_id"],
                            "title": item["title"],
                            "snippet": item["text"][:320],
                            "citation": f"[{item['source_id']}]",
                        }
                        for item in results
                    ],
                    "returned_source_ids": [item["source_id"] for item in results],
                    "retrieval_backend": "frozen_bm25_replay_v3",
                },
                call_id=search_id,
            )
        )
        read_id = f"call_{stable_hash(f'{row_id}:read:{step}')[:20]}"
        messages.append(assistant_tool_call("knowledge_read", {"source_id": document["source_id"]}, call_id=read_id))
        messages.append(
            tool_observation(
                "knowledge_read",
                {
                    "ok": True,
                    **document,
                    "citation": f"[{document['source_id']}]",
                    "returned_source_ids": [document["source_id"]],
                },
                call_id=read_id,
            )
        )
        citations.append(f"[{document['source_id']}]")
    messages.append(
        {
            "role": "assistant",
            "content": f"Answer: {clean(row['answer'])}. Evidence: {' '.join(citations)}",
        }
    )
    record = make_record(
        record_id=f"2wiki-replay:{row_id}",
        group_id=group_id,
        source_dataset="studyhub_2wiki_replay",
        source_id=row_id,
        task_family="rag_multihop",
        messages=messages,
        tools=openai_tools(["knowledge_search", "knowledge_read"]),
        provenance=source_provenance,
        capability_tags=[
            "rag",
            "multi_hop",
            "citation",
            "long_horizon" if len(support_titles) >= 3 else "short_horizon",
        ],
        quality_tier="oracle_derived_expert_complete",
        environment_origin="frozen_open_corpus_replay",
    )
    record["split_hint"] = split
    record["document_grouping"] = "connected_component_of_support_titles_v1"
    return record if not validate_runtime_trajectory(record) else None


def _wiki_support_titles(row: Mapping[str, Any]) -> set[str]:
    return {clean(title).casefold() for title, _index in json.loads(row["supporting_facts"]) if clean(title)}


def _wiki_component_assignments(
    rows: list[dict[str, Any]],
) -> dict[str, tuple[str, str]]:
    parent = list(range(len(rows)))
    component_size = [1] * len(rows)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if component_size[left_root] < component_size[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        component_size[left_root] += component_size[right_root]

    title_owner: dict[str, int] = {}
    title_sets: list[set[str]] = []
    for index, row in enumerate(rows):
        titles = _wiki_support_titles(row)
        title_sets.append(titles)
        for title in titles:
            if title in title_owner:
                union(index, title_owner[title])
            else:
                title_owner[title] = index

    members: dict[int, list[int]] = {}
    component_titles: dict[int, set[str]] = {}
    for index, titles in enumerate(title_sets):
        root = find(index)
        members.setdefault(root, []).append(index)
        component_titles.setdefault(root, set()).update(titles)
    targets = {
        "train": round(len(rows) * 0.90),
        "validation": round(len(rows) * 0.05),
    }
    targets["protocol_holdout"] = len(rows) - targets["train"] - targets["validation"]
    assigned = {split: 0 for split in targets}
    component_splits: dict[int, str] = {}
    ordered_components = sorted(
        members,
        key=lambda root: (
            -len(members[root]),
            stable_hash("|".join(sorted(component_titles[root])), salt="2wiki-component-order"),
        ),
    )
    split_order = ("train", "validation", "protocol_holdout")
    for root in ordered_components:
        size = len(members[root])
        feasible = [split for split in split_order if assigned[split] + size <= targets[split]]
        choices = feasible or list(split_order)
        split = max(
            choices,
            key=lambda value: (
                (targets[value] - assigned[value]) / max(targets[value], 1),
                -split_order.index(value),
            ),
        )
        component_splits[root] = split
        assigned[split] += size

    assignments: dict[str, tuple[str, str]] = {}
    for root, indices in members.items():
        component_hash = stable_hash(
            "|".join(sorted(component_titles[root])),
            salt="2wiki-support-title-component",
        )[:24]
        group_id = f"2wiki-component:{component_hash}"
        split = component_splits[root]
        for index in indices:
            assignments[str(rows[index]["_id"])] = (group_id, split)
    return assignments


def iter_2wiki(raw_root: Path, source: Mapping[str, Any], limit: int) -> Iterator[dict[str, Any]]:
    path = raw_root / "2wiki/train.parquet"
    source_provenance = provenance(source, raw_files=[path])
    selected = selected_by_hash(_wiki_rows(path), limit, key=lambda row: row["_id"])
    assignments = _wiki_component_assignments(selected)
    for row in selected:
        group_id, split = assignments[str(row["_id"])]
        record = _wiki_record(row, source_provenance, group_id=group_id, split=split)
        if record:
            yield record


def _qasper_answer(answer: Mapping[str, Any]) -> str:
    if answer.get("unanswerable"):
        return "The available paper evidence is insufficient to answer this question."
    if answer.get("free_form_answer"):
        return clean(answer["free_form_answer"])
    if answer.get("extractive_spans"):
        return "; ".join(clean(value) for value in answer["extractive_spans"])
    if answer.get("yes_no") is not None:
        return "Yes." if answer["yes_no"] else "No."
    return ""


def iter_qasper(raw_root: Path, source: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    paths = [raw_root / f"qasper/qasper-{split}-v0.3.json" for split in ("train", "dev")]
    source_provenance = provenance(source, raw_files=paths)
    tools = openai_tools(["knowledge_search", "knowledge_read"])
    for split, path in zip(("train", "dev"), paths, strict=True):
        papers = json.loads(path.read_text(encoding="utf-8"))
        for paper_id, paper in papers.items():
            for qa in paper.get("qas", []):
                question_id = str(qa["question_id"])
                answer = next(
                    (
                        item.get("answer", {})
                        for item in qa.get("answers", [])
                        if _qasper_answer(item.get("answer", {}))
                    ),
                    None,
                )
                if answer is None:
                    continue
                final = _qasper_answer(answer)
                evidence = [clean(value, limit=2200) for value in answer.get("evidence", []) if clean(value)]
                messages: list[dict[str, Any]] = [
                    {
                        "role": "system",
                        "content": (
                            "You are StudyHub Agent. Search the frozen paper, read supporting passages, "
                            "cite supported claims, and abstain when evidence is insufficient."
                        ),
                    },
                    {"role": "user", "content": f"Paper: {clean(paper['title'])}\nQuestion: {clean(qa['question'])}"},
                ]
                search_id = f"call_{stable_hash(f'qasper:{question_id}:search')[:20]}"
                messages.append(
                    assistant_tool_call(
                        "knowledge_search",
                        {"query": clean(qa["question"]), "limit": 5},
                        call_id=search_id,
                    )
                )
                sources = [
                    {
                        "source_id": _source_id("paper", question_id, str(index)),
                        "title": f"{clean(paper['title'])} - evidence {index + 1}",
                        "text": text,
                    }
                    for index, text in enumerate(evidence[:3])
                ]
                messages.append(
                    tool_observation(
                        "knowledge_search",
                        {
                            "ok": True,
                            "query": clean(qa["question"]),
                            "results": [
                                {
                                    "source_id": item["source_id"],
                                    "title": item["title"],
                                    "snippet": item["text"][:320],
                                    "citation": f"[{item['source_id']}]",
                                }
                                for item in sources
                            ],
                            "returned_source_ids": [item["source_id"] for item in sources],
                            "retrieval_backend": "frozen_paper_replay_v3",
                        },
                        call_id=search_id,
                    )
                )
                citations = []
                for index, item in enumerate(sources):
                    read_id = f"call_{stable_hash(f'qasper:{question_id}:read:{index}')[:20]}"
                    messages.append(
                        assistant_tool_call("knowledge_read", {"source_id": item["source_id"]}, call_id=read_id)
                    )
                    messages.append(
                        tool_observation(
                            "knowledge_read",
                            {
                                "ok": True,
                                **item,
                                "citation": f"[{item['source_id']}]",
                                "returned_source_ids": [item["source_id"]],
                            },
                            call_id=read_id,
                        )
                    )
                    citations.append(f"[{item['source_id']}]")
                suffix = f" Evidence: {' '.join(citations)}" if citations else ""
                messages.append({"role": "assistant", "content": final + suffix})
                record = make_record(
                    record_id=f"qasper-replay:{split}:{question_id}",
                    group_id=f"qasper:{split}:{paper_id}",
                    source_dataset="studyhub_qasper_replay",
                    source_id=f"{split}:{question_id}",
                    task_family="paper_grounded_qa",
                    messages=messages,
                    tools=tools,
                    provenance=source_provenance,
                    capability_tags=["rag", "paper_qa", "citation", "abstention" if not sources else "research"],
                    quality_tier="oracle_derived_expert_complete",
                    environment_origin="frozen_open_corpus_replay",
                )
                if not validate_runtime_trajectory(record):
                    yield record


def _material_text(material: Mapping[str, Any]) -> str:
    tags = ", ".join(map(str, material.get("tags", []))) or "未标注"
    fields = [
        f"资料标题：{clean(material.get('title'))}",
        f"资料标签：{tags}",
        f"资料描述：{clean(material.get('description')) or '暂无简介'}",
        f"学校：{clean(material.get('school')) or '未标注'}",
        f"学院：{clean(material.get('college')) or '未标注'}",
        f"专业：{clean(material.get('major')) or '未标注'}",
        f"下载量：{int(material.get('downloadCount') or 0)}",
    ]
    return "\n".join(fields)


def _material_source(material: Mapping[str, Any]) -> dict[str, Any]:
    material_id = int(material["id"])
    return {
        "source_id": f"studyhub-material:{material_id}",
        "material_id": material_id,
        "title": clean(material.get("title")),
        "text": _material_text(material),
    }


def _studyhub_provenance(materials_path: Path) -> dict[str, Any]:
    return {
        "revision": sha256(materials_path),
        "license": "StudyHub internal metadata; free previews only in policy-visible observations",
        "source_url": "https://study-hub.cn",
        "attribution": "StudyHub material catalog backup",
        "raw_files": [{"path": str(materials_path), "sha256": sha256(materials_path)}],
        "transform_version": TRANSFORM_VERSION,
    }


def _material_partitions(materials: list[dict[str, Any]], *, salt: str) -> dict[str, list[dict[str, Any]]]:
    ordered = sorted(materials, key=lambda row: stable_hash(f"{salt}:{row['id']}:split"))
    # Reserve enough material groups for diverse holdouts; trajectory quotas remain 90/5/5.
    train_end = max(2, round(len(ordered) * 0.80))
    validation_end = max(train_end + 2, round(len(ordered) * 0.90))
    validation_end = min(validation_end, len(ordered) - 2)
    return {
        "train": ordered[:train_end],
        "validation": ordered[train_end:validation_end],
        "protocol_holdout": ordered[validation_end:],
    }


def _ordinal_split(ordinal: int) -> str:
    bucket = ordinal % 20
    if bucket < 18:
        return "train"
    return "validation" if bucket == 18 else "protocol_holdout"


def _material_pairs(
    materials: list[dict[str, Any]], limit: int, *, salt: str
) -> Iterator[tuple[int, str, dict[str, Any], dict[str, Any]]]:
    partitions = _material_partitions(materials, salt="shared-studyhub-material")
    seen: set[tuple[str, int, int, int]] = set()
    ordinal = 0
    attempt = 0
    while ordinal < limit and attempt < limit * 20:
        split = _ordinal_split(ordinal)
        pool = partitions[split]
        first = int(stable_hash(f"{salt}:a:{attempt}")[:12], 16) % len(pool)
        second = int(stable_hash(f"{salt}:b:{attempt}")[:12], 16) % len(pool)
        variant = int(stable_hash(f"{salt}:v:{attempt}")[:8], 16) % 1000
        attempt += 1
        if first == second:
            continue
        key = (split, int(pool[first]["id"]), int(pool[second]["id"]), variant)
        if key in seen:
            continue
        seen.add(key)
        yield ordinal, split, pool[first], pool[second]
        ordinal += 1
    if ordinal < limit:
        raise RuntimeError(f"could only build {ordinal}/{limit} unique {salt} material pairs")


def _search_observation(query: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "query": query,
        "results": [
            {
                "source_id": item["source_id"],
                "material_id": item["material_id"],
                "title": item["title"],
                "snippet": item["text"][:320],
                "citation": f"[{item['source_id']}]",
            }
            for item in sources
        ],
        "returned_source_ids": [item["source_id"] for item in sources],
        "retrieval_backend": "studyhub_metadata_replay_v3",
    }


def iter_studyhub_metadata(
    materials: list[dict[str, Any]], provenance_record: Mapping[str, Any], limit: int
) -> Iterator[dict[str, Any]]:
    prompts = (
        "帮我比较《{a}》和《{b}》，优先推荐更适合当前复习的一份，并引用资料信息。",
        "我要找与 {tag} 相关的资料。请核对《{a}》与《{b}》的简介后给出选择。",
        "请从两份候选资料中选择一份用于期末复习：{a}；{b}。不要只看下载量。",
        "核对两份 StudyHub 资料的标题、标签和简介，再告诉我先看哪一份：{a} / {b}。",
    )
    focuses = ("概念框架", "公式条件", "真题训练", "考前查漏", "章节预习", "错题复盘")
    tools = openai_tools(["knowledge_search", "knowledge_read"])
    for ordinal, split, first, second in _material_pairs(materials, limit, salt="metadata"):
        target, alternative = sorted(
            (first, second),
            key=lambda row: (
                len(row.get("description") or ""),
                len(row.get("tags", [])),
                int(row.get("downloadCount") or 0),
            ),
            reverse=True,
        )
        sources = [_material_source(target), _material_source(alternative)]
        tag = next(iter(target.get("tags", [])), clean(target.get("title")))
        query = f"{clean(target.get('title'))} {tag}"
        call_search = f"call_{stable_hash(f'metadata:{ordinal}:search')[:20]}"
        call_read = f"call_{stable_hash(f'metadata:{ordinal}:read')[:20]}"
        focus = focuses[(ordinal // 20) % len(focuses)]
        prompt = prompts[ordinal % len(prompts)].format(a=clean(first["title"]), b=clean(second["title"]), tag=tag)
        prompt = f"{prompt} 当前复习侧重是{focus}。"
        messages = [
            {"role": "system", "content": "你是 StudyHub Agent。先检索再读取资料信息，仅推荐可公开访问的资料。"},
            {"role": "user", "content": prompt},
            assistant_tool_call("knowledge_search", {"query": query, "limit": 5}, call_id=call_search),
            tool_observation("knowledge_search", _search_observation(query, sources), call_id=call_search),
            assistant_tool_call("knowledge_read", {"source_id": sources[0]["source_id"]}, call_id=call_read),
            tool_observation(
                "knowledge_read",
                {"ok": True, **sources[0], "citation": f"[{sources[0]['source_id']}]"},
                call_id=call_read,
            ),
            {
                "role": "assistant",
                "content": (
                    f"围绕{focus}，建议先看《{sources[0]['title']}》，"
                    "因为它的简介和标签与当前目标更匹配。"
                    f"[{sources[0]['source_id']}]"
                ),
            },
        ]
        record = make_record(
            record_id=f"studyhub-metadata:{ordinal:06d}",
            group_id=f"studyhub-material:{int(target['id'])}",
            source_dataset="studyhub_metadata_replay",
            source_id=str(target["id"]),
            task_family="material_search_and_compare",
            messages=messages,
            tools=tools,
            provenance=provenance_record,
            capability_tags=["rag", "recommendation", "citation"],
            quality_tier="deterministic_fixture_complete",
            environment_origin="studyhub_catalog_replay",
        )
        record["split_hint"] = split
        if not validate_runtime_trajectory(record):
            yield record


def iter_studyhub_memory(
    materials: list[dict[str, Any]], provenance_record: Mapping[str, Any], limit: int
) -> Iterator[dict[str, Any]]:
    tools = openai_tools(["personal_memory_search", "knowledge_search", "knowledge_read"])
    preferences = (
        "我更适合先看带解析的资料，再做真题。",
        "我希望先用短笔记建立框架，再进入完整教材。",
        "我正在冲刺期末，优先选择高相关度的复习资料。",
        "我不希望仅按热度推荐，先看标签和简介是否匹配。",
    )
    requests = (
        "先读取我的当前学习偏好，再在《{a}》和《{b}》之间推荐一份，并说明资料证据。",
        "比较《{a}》与《{b}》。请解释当前用户记忆如何影响选择，但不要让偏好覆盖资料事实。",
        "我需要在《{a}》和《{b}》中选一份。只使用我的隔离记忆做个性化，再核对资料信息。",
        "不要只按热度判断《{a}》和《{b}》；结合我的学习方式与资料简介给出一个选择。",
        "检查我的近期学习偏好，并判断《{a}》或《{b}》哪份更适合作为下一步资料。",
        "为《{a}》和《{b}》做个性化比较；若记忆与资料事实冲突，以资料证据为准。",
        "请从《{a}》与《{b}》中选一份复习资料，同时分别说明偏好依据和资料依据。",
        "读取当前用户的学习习惯后，比较《{a}》和《{b}》，不要使用其他用户信息。",
        "我想减少无效复习。结合我的偏好与《{a}》《{b}》的资料说明，推荐更匹配的一份。",
        "先确认个人记忆是否与本次选资料相关，再比较《{a}》和《{b}》并给出有引用的建议。",
    )
    for ordinal, split, first, second in _material_pairs(materials, limit, salt="memory"):
        preference = preferences[(ordinal // 20) % len(preferences)]
        request = requests[(ordinal // 20) % len(requests)].format(a=clean(first["title"]), b=clean(second["title"]))
        target = first if ordinal % 2 == 0 else second
        sources = [_material_source(target), _material_source(second if target is first else first)]
        memory_id = f"memory:{stable_hash(f'memory:{ordinal}')[:14]}"
        memory_call = f"call_{stable_hash(f'memory:{ordinal}:memory')[:20]}"
        search_call = f"call_{stable_hash(f'memory:{ordinal}:search')[:20]}"
        read_call = f"call_{stable_hash(f'memory:{ordinal}:read')[:20]}"
        query = clean(target["title"])
        messages = [
            {
                "role": "system",
                "content": "你是 StudyHub Agent。个性化推荐只能使用当前用户的隔离记忆，并用资料证据核对。",
            },
            {
                "role": "user",
                "content": request,
            },
            assistant_tool_call("personal_memory_search", {"query": "学习偏好", "limit": 5}, call_id=memory_call),
            tool_observation(
                "personal_memory_search",
                {"ok": True, "results": [{"source_id": memory_id, "content": preference, "scope": "current_user"}]},
                call_id=memory_call,
            ),
            assistant_tool_call("knowledge_search", {"query": query, "limit": 5}, call_id=search_call),
            tool_observation("knowledge_search", _search_observation(query, sources), call_id=search_call),
            assistant_tool_call("knowledge_read", {"source_id": sources[0]["source_id"]}, call_id=read_call),
            tool_observation("knowledge_read", {"ok": True, **sources[0]}, call_id=read_call),
            {
                "role": "assistant",
                "content": (
                    f"你的当前偏好是“{preference}”据此建议《{sources[0]['title']}》；"
                    f"该选择同时有当前用户记忆和资料信息支持。[{sources[0]['source_id']}]"
                ),
            },
        ]
        record = make_record(
            record_id=f"studyhub-memory:{ordinal:06d}",
            group_id=f"studyhub-material:{int(target['id'])}",
            source_dataset="studyhub_memory_replay",
            source_id=str(target["id"]),
            task_family="memory_rag_composition",
            messages=messages,
            tools=tools,
            provenance=provenance_record,
            capability_tags=["memory", "rag", "personalization", "citation"],
            quality_tier="deterministic_fixture_complete",
            environment_origin="studyhub_memory_sandbox",
        )
        record["split_hint"] = split
        if not validate_runtime_trajectory(record):
            yield record


def iter_studyhub_acl(
    free: list[dict[str, Any]], paid: list[dict[str, Any]], provenance_record: Mapping[str, Any], limit: int
) -> Iterator[dict[str, Any]]:
    tools = openai_tools(["knowledge_read", "knowledge_search"])
    prompts = (
        "我在准备{need}，共享引用 {private_id}（{private_title}）可能有用；"
        "如果无权读取，请找一份关于{topic}的公开资料替代。",
        "为了{need}，请核对 {private_id}（{private_title}）。遇到权限限制时不要推测内容，改用{topic}相关的公开资料。",
        "我拿到引用 {private_id}，想用于{need}，但不确定权限。若读取失败，请给出{topic}方向的安全替代资料。",
        "先检查 {private_id}（{private_title}）是否可访问；如果被拒绝，继续检索公开来源支持{need}。",
        "目标是{need}。不要绕过 {private_id} 的权限；请在拒绝后为{topic}寻找公开替代。",
        "请为{need}核验引用 {private_id}。如果它受限，明确说明并改用《{topic}》相关公开资料。",
    )
    needs = (
        "期末复习",
        "章节预习",
        "公式查漏",
        "真题训练",
        "错题复盘",
        "课程项目",
        "实验准备",
        "口试准备",
        "概念辨析",
        "知识图谱整理",
    )
    free_partitions = _material_partitions(free, salt="shared-studyhub-material")
    paid_partitions = _material_partitions(paid, salt="shared-studyhub-restricted")
    for ordinal in range(limit):
        split = _ordinal_split(ordinal)
        free_pool = free_partitions[split]
        paid_pool = paid_partitions[split]
        restricted = paid_pool[int(stable_hash(f"acl:paid:{ordinal}")[:12], 16) % len(paid_pool)]
        alternative = free_pool[int(stable_hash(f"acl:free:{ordinal}")[:12], 16) % len(free_pool)]
        private_id = f"paid-source:{int(restricted['id'])}"
        public = _material_source(alternative)
        need = needs[(ordinal // 20) % len(needs)]
        read_private = f"call_{stable_hash(f'acl:{ordinal}:private')[:20]}"
        search_public = f"call_{stable_hash(f'acl:{ordinal}:search')[:20]}"
        read_public = f"call_{stable_hash(f'acl:{ordinal}:read')[:20]}"
        query = clean(alternative["title"])
        messages = [
            {
                "role": "system",
                "content": "你是 StudyHub Agent。不得暴露付费或无权资料内容；权限失败后只能寻找公开替代。",
            },
            {
                "role": "user",
                "content": prompts[ordinal % len(prompts)].format(
                    private_id=private_id,
                    private_title=clean(restricted["title"]),
                    topic=clean(alternative["title"]),
                    need=need,
                ),
            },
            assistant_tool_call("knowledge_read", {"source_id": private_id}, call_id=read_private),
            tool_observation(
                "knowledge_read",
                {
                    "ok": False,
                    "error": "permission_denied",
                    "source_id": private_id,
                    "recovery_hint": "Search for an ACL-authorized alternative.",
                },
                call_id=read_private,
            ),
            assistant_tool_call("knowledge_search", {"query": query, "limit": 5}, call_id=search_public),
            tool_observation("knowledge_search", _search_observation(query, [public]), call_id=search_public),
            assistant_tool_call("knowledge_read", {"source_id": public["source_id"]}, call_id=read_public),
            tool_observation("knowledge_read", {"ok": True, **public}, call_id=read_public),
            {
                "role": "assistant",
                "content": (
                    f"原共享引用无权读取，我没有使用其内容。为完成{need}，"
                    f"可改用公开资料《{public['title']}》。"
                    f"[{public['source_id']}]"
                ),
            },
        ]
        record = make_record(
            record_id=f"studyhub-acl:{ordinal:06d}",
            group_id=f"studyhub-acl:{int(restricted['id'])}:{int(alternative['id'])}",
            source_dataset="studyhub_acl_recovery",
            source_id=f"{restricted['id']}:{alternative['id']}",
            task_family="permission_recovery",
            messages=messages,
            tools=tools,
            provenance=provenance_record,
            capability_tags=["acl", "recovery", "rag", "citation"],
            quality_tier="deterministic_fixture_complete",
            environment_origin="studyhub_acl_sandbox",
        )
        record["split_hint"] = split
        if not validate_runtime_trajectory(record):
            yield record


def iter_studyhub_web(
    materials: list[dict[str, Any]], provenance_record: Mapping[str, Any], limit: int
) -> Iterator[dict[str, Any]]:
    tools = openai_tools(["knowledge_search", "web_search", "web_fetch"])
    verification_goals = ("核对资料范围", "确认公开可访问性", "比较页面简介", "检查课程相关性")
    for ordinal, split, material, comparison in _material_pairs(materials, limit, salt="web"):
        material_id = int(material["id"])
        comparison_id = int(comparison["id"])
        query = f"StudyHub {clean(material['title'])} {clean(comparison['title'])} public overview"
        url = f"https://study-hub.cn/materials/{material_id}"
        comparison_url = f"https://study-hub.cn/materials/{comparison_id}"
        source_id = f"web-material:{material_id}"
        knowledge_call = f"call_{stable_hash(f'web:{ordinal}:knowledge')[:20]}"
        search_call = f"call_{stable_hash(f'web:{ordinal}:search')[:20]}"
        fetch_call = f"call_{stable_hash(f'web:{ordinal}:fetch')[:20]}"
        verification_goal = verification_goals[(ordinal // 20) % len(verification_goals)]
        messages = [
            {
                "role": "system",
                "content": "你是 StudyHub Agent。本地证据为空时可以使用受控 Web 搜索，并引用实际抓取页面。",
            },
            {
                "role": "user",
                "content": (
                    f"核对《{material['title']}》与《{comparison['title']}》的公开页面；"
                    f"本地找不到时再查网页，重点{verification_goal}，并先说明第一份资料。"
                ),
            },
            assistant_tool_call("knowledge_search", {"query": query, "limit": 5}, call_id=knowledge_call),
            tool_observation(
                "knowledge_search",
                {"ok": True, "query": query, "results": [], "returned_source_ids": []},
                call_id=knowledge_call,
            ),
            assistant_tool_call("web_search", {"query": query, "limit": 5}, call_id=search_call),
            tool_observation(
                "web_search",
                {
                    "ok": True,
                    "query": query,
                    "results": [
                        {"title": clean(material["title"]), "url": url, "source_id": source_id},
                        {
                            "title": clean(comparison["title"]),
                            "url": comparison_url,
                            "source_id": f"web-material:{comparison_id}",
                        },
                    ],
                },
                call_id=search_call,
            ),
            assistant_tool_call("web_fetch", {"url": url}, call_id=fetch_call),
            tool_observation(
                "web_fetch",
                {"ok": True, "url": url, "source_id": source_id, "text": _material_text(material)},
                call_id=fetch_call,
            ),
            {
                "role": "assistant",
                "content": (
                    f"公开页面显示该资料为《{clean(material['title'])}》，"
                    f"已据此{verification_goal}，可按页面简介判断是否适合当前目标。[{source_id}]"
                ),
            },
        ]
        record = make_record(
            record_id=f"studyhub-web:{ordinal:06d}",
            group_id=f"studyhub-material:{material_id}",
            source_dataset="studyhub_web_fallback",
            source_id=str(material_id),
            task_family="web_fallback",
            messages=messages,
            tools=tools,
            provenance=provenance_record,
            capability_tags=["web", "recovery", "citation", "long_horizon"],
            quality_tier="deterministic_fixture_complete",
            environment_origin="frozen_web_replay",
        )
        record["split_hint"] = split
        if not validate_runtime_trajectory(record):
            yield record


def iter_studyhub_state(
    materials: list[dict[str, Any]], provenance_record: Mapping[str, Any], limit: int
) -> Iterator[dict[str, Any]]:
    tools = openai_tools(["knowledge_search", "knowledge_read", "study_plan_update", "material_bookmark_add"])
    planning_goals = (
        "建立本周复习节奏",
        "安排考前查漏",
        "完成章节预习",
        "组织公式复盘",
        "推进真题训练",
        "准备课程项目",
        "安排错题回顾",
        "建立概念框架",
        "准备口试表达",
        "平衡两份资料的阅读时间",
    )
    request_templates = (
        "为了{goal}，比较《{a}》和《{b}》，把第一份加入收藏，并为两份资料安排本周 {minutes} 分钟复习。",
        "请先核对《{a}》与《{b}》，再完成收藏和学习计划更新；目标是{goal}，总时长 {minutes} 分钟。",
        "我想{goal}。请比较《{a}》《{b}》，收藏第一份，并把两份资料写入 {minutes} 分钟的本周计划。",
        "在隔离学习账户中，为{goal}处理《{a}》和《{b}》：核对后收藏第一份，再更新 {minutes} 分钟计划。",
    )
    for ordinal, split, material, companion in _material_pairs(materials, limit, salt="state"):
        source = _material_source(material)
        companion_source = _material_source(companion)
        weekly_minutes = 60 + 15 * (ordinal % 13)
        goal = planning_goals[(ordinal // 20) % len(planning_goals)]
        request = request_templates[ordinal % len(request_templates)].format(
            goal=goal,
            a=clean(material["title"]),
            b=clean(companion["title"]),
            minutes=weekly_minutes,
        )
        search_call = f"call_{stable_hash(f'state:{ordinal}:search')[:20]}"
        read_call = f"call_{stable_hash(f'state:{ordinal}:read')[:20]}"
        plan_call = f"call_{stable_hash(f'state:{ordinal}:plan')[:20]}"
        bookmark_call = f"call_{stable_hash(f'state:{ordinal}:bookmark')[:20]}"
        messages = [
            {
                "role": "system",
                "content": "你是 StudyHub Agent。写操作只在隔离任务沙箱执行，并在工具确认后再向用户报告完成。",
            },
            {
                "role": "user",
                "content": request,
            },
            assistant_tool_call(
                "knowledge_search", {"query": clean(material["title"]), "limit": 5}, call_id=search_call
            ),
            tool_observation(
                "knowledge_search",
                _search_observation(clean(material["title"]), [source, companion_source]),
                call_id=search_call,
            ),
            assistant_tool_call("knowledge_read", {"source_id": source["source_id"]}, call_id=read_call),
            tool_observation("knowledge_read", {"ok": True, **source}, call_id=read_call),
            assistant_tool_call(
                "study_plan_update",
                {
                    "topic": clean(material["title"], limit=100),
                    "weekly_minutes": weekly_minutes,
                    "resource_ids": [int(material["id"]), int(companion["id"])],
                },
                call_id=plan_call,
            ),
            tool_observation(
                "study_plan_update",
                {"ok": True, "postcondition": "study_plan_updated", "weekly_minutes": weekly_minutes},
                call_id=plan_call,
            ),
            assistant_tool_call("material_bookmark_add", {"material_id": int(material["id"])}, call_id=bookmark_call),
            tool_observation(
                "material_bookmark_add",
                {"ok": True, "postcondition": "material_bookmarked", "material_id": int(material["id"])},
                call_id=bookmark_call,
            ),
            {
                "role": "assistant",
                "content": (
                    f"已在隔离学习账户中收藏《{material['title']}》，"
                    f"并安排本周 {weekly_minutes} 分钟复习。[{source['source_id']}]"
                ),
            },
        ]
        record = make_record(
            record_id=f"studyhub-state:{ordinal:06d}",
            group_id=f"studyhub-material:{int(material['id'])}",
            source_dataset="studyhub_state_tools",
            source_id=str(material["id"]),
            task_family="state_multistep_postcondition",
            messages=messages,
            tools=tools,
            provenance=provenance_record,
            capability_tags=["state", "function_calling", "rag", "long_horizon"],
            quality_tier="deterministic_fixture_complete",
            environment_origin="studyhub_state_sandbox",
        )
        record["split_hint"] = split
        if not validate_runtime_trajectory(record):
            yield record


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=project / "data_registry/open_sft_sources.json")
    parser.add_argument("--raw-root", type=Path, default=project / "datasets/raw/open_source")
    parser.add_argument(
        "--materials", type=Path, default=project.parent / "backup/oss_materials/metadata/materials.json"
    )
    parser.add_argument(
        "--benchmark-inventory",
        type=Path,
        default=project / "artifacts/benchmark-v2/studyhub-agent-v2/source-inventory.jsonl",
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/manifest.json",
    )
    parser.add_argument("--output", type=Path, default=project / "datasets/interim/runtime_sft_v3/candidates.jsonl")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale every source pool for smoke builds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 < args.scale <= 1:
        raise ValueError("--scale must be in (0, 1]")
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    sources = {row["id"]: row for row in registry["sources"]}
    limits = {name: max(1, round(value * args.scale)) for name, value in DEFAULT_POOL_LIMITS.items()}
    frozen_benchmark = benchmark_lock(args.benchmark_manifest, args.benchmark_inventory)
    inventory = [json.loads(line) for line in args.benchmark_inventory.read_text(encoding="utf-8").splitlines()]
    benchmark_material_ids = {int(row["material_id"]) for row in inventory if row.get("material_id") is not None}
    materials = json.loads(args.materials.read_text(encoding="utf-8"))
    remaining = [row for row in materials if int(row["id"]) not in benchmark_material_ids]
    free = [row for row in remaining if row.get("free") is True and float(row.get("price") or 0) <= 0]
    paid = [row for row in remaining if row not in free]
    if len(free) < 20 or not paid:
        raise RuntimeError("insufficient benchmark-disjoint StudyHub material metadata")
    studyhub_provenance = _studyhub_provenance(args.materials)

    loaders: list[tuple[str, Iterable[dict[str, Any]]]] = [
        ("toolace", iter_toolace(args.raw_root, sources["toolace"])),
        ("hermes_function_calling", iter_hermes(args.raw_root, sources["hermes_function_calling"])),
        ("coig_exam", iter_coig(args.raw_root, sources["coig_exam"])),
        (
            "studyhub_2wiki_replay",
            iter_2wiki(args.raw_root, sources["2wiki"], limits["studyhub_2wiki_replay"]),
        ),
        ("studyhub_qasper_replay", iter_qasper(args.raw_root, sources["qasper"])),
        (
            "studyhub_metadata_replay",
            iter_studyhub_metadata(free, studyhub_provenance, limits["studyhub_metadata_replay"] * 2),
        ),
        (
            "studyhub_memory_replay",
            iter_studyhub_memory(free, studyhub_provenance, limits["studyhub_memory_replay"] * 2),
        ),
        (
            "studyhub_acl_recovery",
            iter_studyhub_acl(free, paid, studyhub_provenance, limits["studyhub_acl_recovery"] * 2),
        ),
        (
            "studyhub_web_fallback",
            iter_studyhub_web(free, studyhub_provenance, limits["studyhub_web_fallback"] * 2),
        ),
        (
            "studyhub_state_tools",
            iter_studyhub_state(free, studyhub_provenance, limits["studyhub_state_tools"] * 2),
        ),
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    runtime_native = 0
    complete = 0
    content_hashes: set[str] = set()
    with args.output.open("w", encoding="utf-8") as stream:
        for source_name, rows in loaders:
            limit = limits[source_name]
            source_count = 0
            for row in rows:
                if row["content_sha256"] in content_hashes:
                    continue
                content_hashes.add(row["content_sha256"])
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                source_count += 1
                counts[source_name] += 1
                runtime_native += int(row["runtime_native"])
                complete += int(row["trajectory_status"] == "complete")
                if source_count >= limit:
                    break
            if source_count < limit:
                raise RuntimeError(f"insufficient {source_name} candidates: {source_count}/{limit}")
    manifest = {
        "schema_version": "studyhub.runtime-sft-candidate-manifest.v3",
        "transform_version": TRANSFORM_VERSION,
        "status": "BUILT_NOT_SELECTED",
        "scale": args.scale,
        "total": sum(counts.values()),
        "source_counts": dict(sorted(counts.items())),
        "runtime_native_count": runtime_native,
        "runtime_native_share": round(runtime_native / max(sum(counts.values()), 1), 6),
        "complete_count": complete,
        "benchmark_material_ids_excluded": len(benchmark_material_ids),
        "studyhub_materials_available": {"free": len(free), "restricted": len(paid)},
        "output_sha256": sha256(args.output),
        "registry_sha256": sha256(args.registry),
        "materials_sha256": sha256(args.materials),
        "benchmark_inventory_sha256": sha256(args.benchmark_inventory),
        "benchmark_lock": frozen_benchmark,
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
