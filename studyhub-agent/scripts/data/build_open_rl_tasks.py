#!/usr/bin/env python3
"""Build isolated Agent RL tasks, frozen environments, and hidden verifiers."""

from __future__ import annotations

import argparse
import ast
import hashlib
import heapq
import json
import re
import shutil
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "studyhub.open-rl-dataset.v1"
TRANSFORM_VERSION = "open-agent-rl-v1"
SOURCE_TARGETS = {
    "toolace": {"train": 333, "validation": 67},
    "hermes_function_calling": {"train": 334, "validation": 66},
    "2wiki": {"train": 833, "validation": 167},
    "qasper": {"train": 500, "validation": 100},
}


def clean(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def stable_digest(value: str, *, salt: str = TRANSFORM_VERSION) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def normalize_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if item is None:
            continue
        if key == "type" and item == "dict":
            item = "object"
        result[key] = normalize_json_schema(item)
    return result


def parse_toolace_tools(system: str) -> list[dict[str, Any]]:
    start = system.find("[")
    if start < 0:
        return []
    try:
        rows, _ = json.JSONDecoder().raw_decode(system[start:])
    except json.JSONDecodeError:
        return []
    tools = []
    for row in rows if isinstance(rows, list) else []:
        name = clean(row.get("name"))
        parameters = normalize_json_schema(row.get("parameters") or {"type": "object", "properties": {}})
        if name and isinstance(parameters, dict):
            tools.append(
                {
                    "original_name": name,
                    "description": clean(row.get("description") or row.get("desc") or name),
                    "parameters": parameters,
                }
            )
    return tools


def parse_hermes_tools(value: Any) -> list[dict[str, Any]]:
    try:
        rows = parse_json(value)
    except (TypeError, json.JSONDecodeError):
        return []
    tools = []
    for row in rows if isinstance(rows, list) else []:
        function = row.get("function", row)
        name = clean(function.get("name"))
        parameters = normalize_json_schema(function.get("parameters") or {"type": "object", "properties": {}})
        if name and isinstance(parameters, dict):
            tools.append(
                {
                    "original_name": name,
                    "description": clean(function.get("description") or name),
                    "parameters": parameters,
                }
            )
    return tools


def parse_keyword_arguments(value: str) -> dict[str, Any] | None:
    try:
        expression = ast.parse(f"f({value})", mode="eval").body
        if not isinstance(expression, ast.Call) or expression.args:
            return None
        result = {}
        for keyword in expression.keywords:
            if keyword.arg is None:
                return None
            result[keyword.arg] = ast.literal_eval(keyword.value)
        json.dumps(result)
        return result
    except (SyntaxError, ValueError, TypeError):
        return None


def parse_toolace_calls(value: str, tool_names: list[str]) -> list[dict[str, Any]]:
    positions = []
    for name in tool_names:
        marker = name + "("
        start = value.find(marker)
        while start >= 0:
            positions.append((start, -len(name), name))
            start = value.find(marker, start + 1)
    calls = []
    cursor = 0
    for start, _, name in sorted(positions):
        if start < cursor:
            continue
        open_index = start + len(name)
        depth = 1
        quote = None
        escaped = False
        index = open_index + 1
        while index < len(value) and depth:
            character = value[index]
            if quote:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    quote = None
            elif character in {"'", '"'}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            index += 1
        if depth:
            continue
        arguments = parse_keyword_arguments(value[open_index + 1 : index - 1])
        if arguments is None:
            continue
        calls.append({"original_name": name, "arguments": arguments})
        cursor = index
    return calls


def parse_hermes_tagged_json(value: str, tag: str) -> list[dict[str, Any]]:
    pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.DOTALL)
    rows = []
    for match in pattern.finditer(value):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def safe_tool_name(original: str, task_suffix: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", original).strip("_").lower() or "tool"
    if not re.match(r"[A-Za-z_]", slug):
        slug = "tool_" + slug
    return f"{slug[:45]}_{task_suffix[:10]}"[:64]


def task_identity(source: str, source_id: str) -> tuple[str, str]:
    suffix = stable_digest(f"{source}:{source_id}")[:12]
    return f"rl-{source.replace('_', '-')}-{suffix}", suffix


def finalize_function_candidate(
    *,
    source: str,
    source_id: str,
    group_id: str,
    user_request: str,
    tools: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    expected_final: str,
) -> dict[str, Any] | None:
    task_id, suffix = task_identity(source, source_id)
    tool_map = {tool["original_name"]: safe_tool_name(tool["original_name"], suffix) for tool in tools}
    if not calls or any(call["original_name"] not in tool_map for call in calls):
        return None
    public_tools = [
        {
            "name": tool_map[tool["original_name"]],
            "description": tool["description"],
            "parameters": tool["parameters"],
            "capability": "function_call",
        }
        for tool in tools
    ]
    expected_calls = [{"name": tool_map[call["original_name"]], "arguments": call["arguments"]} for call in calls]
    response_queues: dict[str, list[Any]] = defaultdict(list)
    for response in responses:
        response_queues[clean(response.get("original_name"))].append(response.get("result"))
    routes = []
    for call in calls:
        queue = response_queues[call["original_name"]]
        result = queue.pop(0) if queue else {"ok": True, "arguments": call["arguments"]}
        routes.append(
            {
                "name": tool_map[call["original_name"]],
                "arguments": call["arguments"],
                "result": result,
            }
        )
    max_tool_calls = min(8, max(2, len(expected_calls) + 1))
    return {
        "source_dataset": source,
        "source_id": source_id,
        "group_id": group_id,
        "task_id": task_id,
        "family": "function_calling",
        "difficulty": "hard" if len(expected_calls) >= 3 else "medium",
        "user_request": clean(user_request),
        "tools": public_tools,
        "documents": [],
        "fixture": {"schema_version": "studyhub.fixture-environment.v1", "routes": routes},
        "verifier": {
            "schema_version": "studyhub.hidden-verifier.v1",
            "family": "function_calling",
            "expected_calls": expected_calls,
            "expected_answers": [clean(expected_final)] if clean(expected_final) else [],
            "gold_source_ids": [],
            "citations_required": False,
        },
        "max_steps": min(10, max_tool_calls + 2),
        "max_tool_calls": max_tool_calls,
    }


def iter_toolace(root: Path, excluded_ids: set[str]) -> Iterable[dict[str, Any]]:
    rows = json.loads((root / "toolace/data.json").read_text(encoding="utf-8"))
    for index, row in enumerate(rows):
        source_id = str(index)
        if source_id in excluded_ids:
            continue
        tools = parse_toolace_tools(row.get("system", ""))
        if not tools:
            continue
        conversations = row.get("conversations", [])
        for message_index, message in enumerate(conversations[:-1]):
            if message.get("from") != "assistant" or conversations[message_index + 1].get("from") != "tool":
                continue
            previous_users = [
                item.get("value", "") for item in conversations[:message_index] if item.get("from") == "user"
            ]
            if not previous_users:
                break
            calls = parse_toolace_calls(message.get("value", ""), [tool["original_name"] for tool in tools])
            try:
                response_rows = json.loads(conversations[message_index + 1].get("value", ""))
            except json.JSONDecodeError:
                response_rows = []
            responses = [
                {"original_name": clean(item.get("name")), "result": item.get("results", item)}
                for item in response_rows
                if isinstance(item, dict)
            ]
            final = ""
            if message_index + 2 < len(conversations) and conversations[message_index + 2].get("from") == "assistant":
                final = conversations[message_index + 2].get("value", "")
            candidate = finalize_function_candidate(
                source="toolace",
                source_id=source_id,
                group_id=source_id,
                user_request=previous_users[-1],
                tools=tools,
                calls=calls,
                responses=responses,
                expected_final=final,
            )
            if candidate:
                yield candidate
            break


def iter_hermes(root: Path, excluded_ids: set[str]) -> Iterable[dict[str, Any]]:
    filename = "func-calling.json"
    rows = json.loads((root / "hermes_function_calling" / filename).read_text(encoding="utf-8"))
    for index, row in enumerate(rows):
        source_id = f"{filename}:{row.get('id', index)}"
        if source_id in excluded_ids:
            continue
        tools = parse_hermes_tools(row.get("tools"))
        conversations = row.get("conversations", [])
        user_request = next((item.get("value", "") for item in conversations if item.get("from") == "human"), "")
        call_message = next(
            (
                item.get("value", "")
                for item in conversations
                if item.get("from") == "gpt" and "<tool_call>" in item.get("value", "")
            ),
            "",
        )
        calls = [
            {"original_name": clean(item.get("name")), "arguments": item.get("arguments", {})}
            for item in parse_hermes_tagged_json(call_message, "tool_call")
            if isinstance(item.get("arguments"), dict)
        ]
        response_message = next((item.get("value", "") for item in conversations if item.get("from") == "tool"), "")
        responses = [
            {"original_name": clean(item.get("name")), "result": item.get("content", item)}
            for item in parse_hermes_tagged_json(response_message, "tool_response")
        ]
        final_messages = [
            item.get("value", "")
            for item in conversations
            if item.get("from") == "gpt" and "<tool_call>" not in item.get("value", "")
        ]
        candidate = finalize_function_candidate(
            source="hermes_function_calling",
            source_id=source_id,
            group_id=source_id,
            user_request=user_request,
            tools=tools,
            calls=calls,
            responses=responses,
            expected_final=final_messages[-1] if final_messages else "",
        )
        if candidate:
            yield candidate


def search_tools(suffix: str) -> list[dict[str, Any]]:
    return [
        {
            "name": safe_tool_name("knowledge_search", suffix),
            "description": "Search the frozen task corpus. Use concise keywords and inspect returned source IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
                },
                "required": ["query"],
            },
            "capability": "knowledge_search",
        },
        {
            "name": safe_tool_name("knowledge_read", suffix),
            "description": "Read one source returned by the frozen corpus search tool.",
            "parameters": {
                "type": "object",
                "properties": {"source_id": {"type": "string"}},
                "required": ["source_id"],
            },
            "capability": "knowledge_read",
        },
    ]


def source_id_for(task_id: str, label: str) -> str:
    return "src-" + stable_digest(f"{task_id}:{label}", salt="source-id")[:12]


def iter_2wiki(root: Path, excluded_ids: set[str]) -> Iterable[dict[str, Any]]:
    import pyarrow.parquet as pq

    path = root / "2wiki/train.parquet"
    columns = ["_id", "question", "context", "supporting_facts", "answer"]
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=2048, columns=columns):
        for row in batch.to_pylist():
            source_id = clean(row["_id"])
            if source_id in excluded_ids:
                continue
            task_id, suffix = task_identity("2wiki", source_id)
            try:
                context = parse_json(row["context"])
                supporting = parse_json(row["supporting_facts"])
            except (TypeError, json.JSONDecodeError):
                continue
            documents = []
            title_to_source = {}
            for index, (title, sentences) in enumerate(context):
                text = clean(" ".join(map(str, sentences)))
                if not text:
                    continue
                document_source_id = source_id_for(task_id, f"{index}:{title}")
                title_to_source[title] = document_source_id
                documents.append({"source_id": document_source_id, "title": clean(title), "text": text})
            gold_source_ids = sorted({title_to_source[title] for title, _ in supporting if title in title_to_source})
            if len(gold_source_ids) < 2:
                continue
            tools = search_tools(suffix)
            yield {
                "source_dataset": "2wiki",
                "source_id": source_id,
                "group_id": source_id,
                "task_id": task_id,
                "family": "search_multihop",
                "difficulty": "hard" if len(gold_source_ids) >= 3 else "medium",
                "user_request": clean(row["question"]),
                "tools": tools,
                "documents": documents,
                "fixture": None,
                "verifier": {
                    "schema_version": "studyhub.hidden-verifier.v1",
                    "family": "search_multihop",
                    "expected_calls": [],
                    "expected_answers": [clean(row["answer"])],
                    "gold_source_ids": gold_source_ids,
                    "citations_required": True,
                },
                "max_steps": 10,
                "max_tool_calls": 8,
            }


def qasper_answer(answer: dict[str, Any]) -> str:
    if answer.get("unanswerable"):
        return "The available paper evidence is insufficient to answer the question."
    if answer.get("free_form_answer"):
        return clean(answer["free_form_answer"])
    if answer.get("extractive_spans"):
        return "; ".join(clean(item) for item in answer["extractive_spans"] if clean(item))
    if answer.get("yes_no") is not None:
        return "Yes" if answer["yes_no"] else "No"
    return ""


def evidence_source_ids(evidence: list[str], documents: list[dict[str, str]]) -> list[str]:
    matched = set()
    for raw in evidence:
        needle = clean(raw).casefold()
        if not needle:
            continue
        exact = [doc["source_id"] for doc in documents if needle in doc["text"].casefold()]
        if exact:
            matched.update(exact)
            continue
        needle_tokens = set(re.findall(r"[A-Za-z0-9]+", needle))
        if not needle_tokens:
            continue
        scored = []
        for doc in documents:
            tokens = set(re.findall(r"[A-Za-z0-9]+", doc["text"].casefold()))
            scored.append((len(tokens & needle_tokens) / len(needle_tokens), doc["source_id"]))
        score, source_id = max(scored, default=(0.0, ""))
        if score >= 0.75:
            matched.add(source_id)
    return sorted(matched)


def iter_qasper(root: Path, excluded_groups: set[str]) -> Iterable[dict[str, Any]]:
    for split in ("train", "dev"):
        papers = json.loads((root / f"qasper/qasper-{split}-v0.3.json").read_text(encoding="utf-8"))
        for paper_id, paper in papers.items():
            group_id = f"{split}:{paper_id}"
            if group_id in excluded_groups:
                continue
            source_id = group_id
            task_id, suffix = task_identity("qasper", source_id)
            documents = []
            abstract = clean(paper.get("abstract"))
            if abstract:
                documents.append(
                    {"source_id": source_id_for(task_id, "abstract"), "title": "Abstract", "text": abstract}
                )
            for section_index, section in enumerate(paper.get("full_text", [])):
                section_name = clean(section.get("section_name") or f"Section {section_index + 1}")
                for paragraph_index, paragraph in enumerate(section.get("paragraphs", [])):
                    text = clean(paragraph)
                    if text:
                        documents.append(
                            {
                                "source_id": source_id_for(
                                    task_id, f"{section_index}:{paragraph_index}:{section_name}"
                                ),
                                "title": section_name,
                                "text": text[:8000],
                            }
                        )
            if not documents:
                continue
            qas = sorted(paper.get("qas", []), key=lambda row: stable_digest(clean(row.get("question_id"))))
            for qa in qas:
                answers = [entry.get("answer", {}) for entry in qa.get("answers", [])]
                expected_answers = sorted({qasper_answer(answer) for answer in answers if qasper_answer(answer)})
                answerable = [answer for answer in answers if not answer.get("unanswerable") and qasper_answer(answer)]
                evidence = [clean(item) for answer in answerable for item in answer.get("evidence", []) if clean(item)]
                gold_source_ids = evidence_source_ids(evidence, documents)
                if not expected_answers or (answerable and not gold_source_ids):
                    continue
                tools = search_tools(suffix)
                yield {
                    "source_dataset": "qasper",
                    "source_id": f"{group_id}:{qa.get('question_id')}",
                    "group_id": group_id,
                    "task_id": task_id,
                    "family": "evidence_grounding",
                    "difficulty": "hard",
                    "user_request": clean(qa.get("question")),
                    "tools": tools,
                    "documents": documents,
                    "fixture": None,
                    "verifier": {
                        "schema_version": "studyhub.hidden-verifier.v1",
                        "family": "evidence_grounding",
                        "expected_calls": [],
                        "expected_answers": expected_answers,
                        "gold_source_ids": gold_source_ids,
                        "citations_required": bool(gold_source_ids),
                    },
                    "max_steps": 10,
                    "max_tool_calls": 8,
                }
                break


def load_sft_exclusions(metadata_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    ids: dict[str, set[str]] = defaultdict(set)
    groups: dict[str, set[str]] = defaultdict(set)
    for path in sorted(metadata_root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                source = row["source_dataset"]
                ids[source].add(str(row["source_id"]))
                groups[source].add(str(row.get("group_id", row["source_id"])))
    if sum(map(len, ids.values())) != 3000:
        raise RuntimeError("Expected exactly 3,000 selected SFT records before RL isolation")
    return ids, groups


def top_candidates(rows: Iterable[dict[str, Any]], count: int, source: str) -> list[dict[str, Any]]:
    heap: list[tuple[int, str, dict[str, Any]]] = []
    seen_prompts = set()
    for row in rows:
        prompt_hash = stable_digest(clean(row["user_request"]).casefold(), salt="prompt-content")
        if prompt_hash in seen_prompts:
            continue
        seen_prompts.add(prompt_hash)
        key = int(stable_digest(row["task_id"], salt="rl-selection"), 16)
        item = (-key, row["task_id"], row)
        if len(heap) < count:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    if len(heap) < count:
        raise RuntimeError(f"Insufficient {source} RL candidates: found {len(heap)}, need {count}")
    return [item[2] for item in sorted(heap, key=lambda item: -item[0])]


def public_task(row: dict[str, Any], split: str, source_revision: str) -> dict[str, Any]:
    environment_seed = int(stable_digest(row["task_id"], salt="environment-seed")[:8], 16)
    return {
        "task_id": row["task_id"],
        "family": row["family"],
        "difficulty": row["difficulty"],
        "user_request": row["user_request"],
        "environment_seed": environment_seed,
        "allowed_tools": [tool["name"] for tool in row["tools"]],
        "max_steps": row["max_steps"],
        "max_tool_calls": row["max_tool_calls"],
        "metadata": {
            "schema_version": "studyhub.open-rl-task.v1",
            "source_dataset": row["source_dataset"],
            "source_id": row["source_id"],
            "group_id": row["group_id"],
            "source_revision": source_revision,
            "split": split,
            "environment_id": row["task_id"],
            "verifier_id": row["task_id"],
            "oracle_fields_exposed": False,
        },
        "verifier": {},
    }


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=project / "datasets/raw/open_source")
    parser.add_argument(
        "--sft-metadata", type=Path, default=project / "datasets/processed/open_sft_bootstrap_v2/metadata"
    )
    parser.add_argument("--registry", type=Path, default=project / "data_registry/open_sft_sources.json")
    parser.add_argument("--output", type=Path, default=project / "datasets/processed/open_agent_rl_v1")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        if not args.overwrite:
            raise FileExistsError(f"Output exists; pass --overwrite: {args.output}")
        shutil.rmtree(args.output)
    staging = args.output.with_name(args.output.name + ".building")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    source_registry = {row["id"]: row for row in registry["sources"]}
    excluded_ids, excluded_groups = load_sft_exclusions(args.sft_metadata)
    loaders = {
        "toolace": iter_toolace(args.raw_root, excluded_ids["toolace"]),
        "hermes_function_calling": iter_hermes(args.raw_root, excluded_ids["hermes_function_calling"]),
        "2wiki": iter_2wiki(args.raw_root, excluded_ids["2wiki"]),
        "qasper": iter_qasper(args.raw_root, excluded_groups["qasper"]),
    }

    selected_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "validation": []}
    source_split_counts = {}
    for source, split_targets in SOURCE_TARGETS.items():
        total = sum(split_targets.values())
        selected = top_candidates(loaders[source], total, source)
        selected.sort(key=lambda row: stable_digest(row["task_id"], salt="split-order"))
        offset = 0
        source_split_counts[source] = {}
        for split, target in split_targets.items():
            rows = selected[offset : offset + target]
            selected_by_split[split].extend(rows)
            source_split_counts[source][split] = len(rows)
            offset += target

    environments_dir = staging / "environments"
    fixtures_dir = staging / "fixtures"
    verifiers_dir = staging / "verifiers"
    tasks_dir = staging / "tasks"
    environment_manifest = []
    verifier_hashes = {}
    public_rows = {}
    from datasets import Dataset, DatasetDict

    hf_splits = {}
    for split, rows in selected_by_split.items():
        rows.sort(key=lambda row: stable_digest(row["task_id"], salt=f"order:{split}"))
        tasks = []
        verifiers = []
        for row in rows:
            source_revision = source_registry[row["source_dataset"]]["revision"]
            task = public_task(row, split, source_revision)
            environment = {
                "schema_version": "studyhub.frozen-environment.v1",
                "environment_id": row["task_id"],
                "family": row["family"],
                "tools": row["tools"],
                "documents": row["documents"],
            }
            verifier = {"verifier_id": row["task_id"], "task_id": row["task_id"], **row["verifier"]}
            environment_path = environments_dir / f"{row['task_id']}.json"
            write_json(environment_path, environment)
            fixture_path = None
            if row["fixture"] is not None:
                fixture_path = fixtures_dir / f"{row['task_id']}.json"
                write_json(fixture_path, {"environment_id": row["task_id"], **row["fixture"]})
            environment_manifest.append(
                {
                    "task_id": row["task_id"],
                    "environment_sha256": sha256(environment_path),
                    "fixture_sha256": sha256(fixture_path) if fixture_path else None,
                }
            )
            tasks.append(task)
            verifiers.append(verifier)
        write_jsonl(tasks_dir / f"{split}.jsonl", tasks)
        write_jsonl(verifiers_dir / f"{split}.jsonl", verifiers)
        verifier_hashes[split] = sha256(verifiers_dir / f"{split}.jsonl")
        public_rows[split] = tasks
        hf_splits[split] = Dataset.from_list(tasks)

    DatasetDict(hf_splits).save_to_disk(staging / "hf_dataset")
    write_jsonl(staging / "environment_manifest.jsonl", sorted(environment_manifest, key=lambda row: row["task_id"]))
    task_ids = {split: {row["task_id"] for row in rows} for split, rows in public_rows.items()}
    overlap = len(task_ids["train"] & task_ids["validation"])
    if overlap:
        raise RuntimeError(f"Train/validation task overlap: {overlap}")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "transform_version": TRANSFORM_VERSION,
        "source_targets": SOURCE_TARGETS,
        "source_split_counts": source_split_counts,
        "source_split_counts_by_split": {
            split: {source: counts[split] for source, counts in source_split_counts.items()}
            for split in ("train", "validation")
        },
        "split_counts": {split: len(rows) for split, rows in public_rows.items()},
        "family_counts": {
            split: dict(
                sorted(
                    {
                        family: sum(row["family"] == family for row in rows)
                        for family in {row["family"] for row in rows}
                    }.items()
                )
            )
            for split, rows in public_rows.items()
        },
        "sft_isolation": {
            "metadata_root": str(args.sft_metadata.resolve()),
            "excluded_source_ids": {source: len(values) for source, values in sorted(excluded_ids.items())},
            "excluded_groups": {source: len(values) for source, values in sorted(excluded_groups.items())},
        },
        "oracle_policy": {
            "public_task_verifier_is_empty": True,
            "gold_answer_in_rollout_context": False,
            "gold_tool_sequence_in_rollout_context": False,
            "gold_evidence_labels_in_rollout_context": False,
        },
        "task_overlap": overlap,
        "task_sha256": {split: sha256(tasks_dir / f"{split}.jsonl") for split in public_rows},
        "verifier_sha256": verifier_hashes,
        "environment_manifest_sha256": sha256(staging / "environment_manifest.jsonl"),
        "registry_sha256": sha256(args.registry),
    }
    write_json(staging / "manifest.json", manifest)
    staging.replace(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
