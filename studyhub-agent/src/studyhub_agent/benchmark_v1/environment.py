from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.schema import ENVIRONMENT_SCHEMA_VERSION, load_jsonl
from studyhub_agent.benchmark_v1.tool_contracts import TOOL_SCHEMAS, tool_schemas

_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+")
_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")


def mixed_tokens(value: str) -> list[str]:
    normalized = value.casefold()
    tokens = _LATIN_OR_NUMBER.findall(normalized)
    for run in _CHINESE_RUN.findall(normalized):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    return tokens


class ReplayIndex:
    """Deterministic BM25 index for one frozen replay snapshot."""

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self.rows = list(rows)
        self._frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        document_frequency: Counter[str] = Counter()
        for row in self.rows:
            text = " ".join(
                str(row.get(key, "")) for key in ("title", "text", "content", "snippet", "keywords", "tags")
            )
            frequencies = Counter(mixed_tokens(text))
            self._frequencies.append(frequencies)
            self._lengths.append(sum(frequencies.values()))
            document_frequency.update(frequencies)
        total = len(self.rows)
        self._average_length = sum(self._lengths) / total if total else 0.0
        self._idf = {
            token: math.log(1 + (total - count + 0.5) / (count + 0.5)) for token, count in document_frequency.items()
        }

    def search(self, query: str, *, limit: int) -> list[tuple[float, dict[str, Any]]]:
        if not query.strip() or not self.rows:
            return []
        query_terms = mixed_tokens(query)
        scored: list[tuple[float, str, dict[str, Any]]] = []
        k1 = 1.5
        b = 0.75
        for index, (row, frequencies, length) in enumerate(
            zip(self.rows, self._frequencies, self._lengths, strict=True)
        ):
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                denominator = frequency + k1 * (1 - b + b * length / max(self._average_length, 1e-9))
                score += self._idf.get(term, 0.0) * frequency * (k1 + 1) / denominator
            if score > 0:
                stable_id = str(row.get("source_id") or row.get("url") or row.get("memory_id") or index)
                scored.append((score, stable_id, row))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(round(score, 6), row) for score, _, row in scored[:limit]]


@lru_cache(maxsize=16)
def _load_corpus(path: str) -> tuple[dict[str, Any], ...]:
    return tuple(load_jsonl(path))


@dataclass(slots=True)
class ReplayTrace:
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    policy_errors: list[str] = field(default_factory=list)
    environment_errors: list[str] = field(default_factory=list)
    runtime_errors: list[str] = field(default_factory=list)
    discovered_source_ids: set[str] = field(default_factory=set)
    read_source_ids: set[str] = field(default_factory=set)
    fetched_urls: set[str] = field(default_factory=set)
    denied_source_ids: set[str] = field(default_factory=set)
    state_changes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_calls": list(self.tool_calls),
            "policy_errors": list(self.policy_errors),
            "environment_errors": list(self.environment_errors),
            "runtime_errors": list(self.runtime_errors),
            "discovered_source_ids": sorted(self.discovered_source_ids),
            "read_source_ids": sorted(self.read_source_ids),
            "fetched_urls": sorted(self.fetched_urls),
            "denied_source_ids": sorted(self.denied_source_ids),
            "state_changes": list(self.state_changes),
        }


class ReplayableAgentEnvironment:
    """Open-path, stateful task sandbox shared by evaluation and RL adapters.

    The environment enforces schemas, ACL and deterministic transitions. It does
    not encode an expected tool sequence or a preferred query.
    """

    def __init__(self, environment: dict[str, Any], *, root: Path) -> None:
        if environment.get("schema_version") != ENVIRONMENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported environment schema: {environment.get('schema_version')}")
        self.environment = environment
        self.root = root
        self.task_id = str(environment["task_id"])
        self.identity = dict(environment.get("identity", {}))
        self.trace = ReplayTrace()
        self._tool_names = tuple(str(name) for name in environment.get("available_tools", []))
        tool_schemas(self._tool_names)
        self._max_tool_calls = int(environment.get("max_tool_calls", 16))
        self._tool_occurrences: Counter[str] = Counter()
        self._failure_schedule = list(environment.get("failure_schedule", []))
        corpus_rows: list[dict[str, Any]] = []
        corpus_id = environment.get("corpus_id")
        if corpus_id:
            corpus_path = root / "corpora" / f"{corpus_id}.jsonl"
            corpus_rows.extend(_load_corpus(str(corpus_path.resolve())))
        corpus_rows.extend(dict(row) for row in environment.get("inline_documents", []))
        self._documents = {str(row["source_id"]): dict(row) for row in corpus_rows}
        self._knowledge_index = ReplayIndex(self._documents.values())
        self._web_pages = {str(row["url"]): dict(row) for row in environment.get("web_pages", [])}
        self._web_index = ReplayIndex(self._web_pages.values())
        self._personal_memories = [dict(row) for row in environment.get("personal_memories", [])]
        self._collective_memories = [dict(row) for row in environment.get("collective_memories", [])]
        self._personal_index = ReplayIndex(self._personal_memories)
        self._collective_index = ReplayIndex(self._collective_memories)
        self.state = json.loads(json.dumps(environment.get("initial_state", {}), ensure_ascii=False))

    @classmethod
    def from_root(
        cls,
        root: str | Path,
        split: str,
        task_id: str,
    ) -> ReplayableAgentEnvironment:
        root_path = Path(root).resolve()
        rows = _load_environment_store(str((root_path / "environments" / f"{split}.jsonl").resolve()))
        value = rows.get(task_id)
        if value is None:
            raise KeyError(f"environment not found for {split}/{task_id}")
        return cls(value, root=root_path)

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return tool_schemas(self._tool_names)

    def record_runtime_error(self, code: str) -> None:
        if code not in self.trace.runtime_errors:
            self.trace.runtime_errors.append(code)

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        call: dict[str, Any] = {
            "index": len(self.trace.tool_calls),
            "name": name,
            "arguments": dict(arguments) if isinstance(arguments, dict) else {},
        }
        self.trace.tool_calls.append(call)
        if len(self.trace.tool_calls) > self._max_tool_calls:
            return self._finish(call, self._policy_error("tool_call_budget_exhausted"))
        if name not in self._tool_names or name not in TOOL_SCHEMAS:
            return self._finish(call, self._policy_error("unknown_tool", tool=name))
        try:
            normalized = _validate_arguments(TOOL_SCHEMAS[name]["parameters"], arguments)
        except ValueError as error:
            return self._finish(
                call,
                self._policy_error("invalid_arguments", detail=str(error)),
            )
        call["arguments"] = normalized
        self._tool_occurrences[name] += 1
        injected = self._injected_failure(name, self._tool_occurrences[name])
        if injected is not None:
            return self._finish(call, injected)

        handlers = {
            "knowledge_search": self._knowledge_search,
            "knowledge_read": self._knowledge_read,
            "knowledge_browse": self._knowledge_browse,
            "web_search": self._web_search,
            "web_fetch": self._web_fetch,
            "personal_memory_search": self._personal_memory_search,
            "collective_memory_search": self._collective_memory_search,
            "learning_profile_get": self._learning_profile_get,
            "study_plan_update": self._study_plan_update,
            "material_bookmark_add": self._material_bookmark_add,
            "learning_progress_record": self._learning_progress_record,
        }
        result = handlers[name](normalized)
        return self._finish(call, result)

    def _finish(self, call: dict[str, Any], result: dict[str, Any]) -> str:
        call["ok"] = bool(result.get("ok", False))
        call["error"] = result.get("error")
        call["returned_source_ids"] = list(result.get("returned_source_ids", []))
        call["observation"] = result
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def _injected_failure(self, name: str, occurrence: int) -> dict[str, Any] | None:
        for failure in self._failure_schedule:
            if str(failure.get("tool")) != name or int(failure.get("occurrence", 1)) != occurrence:
                continue
            code = str(failure.get("error_code", "transient_failure"))
            self.trace.environment_errors.append(code)
            return {
                "ok": False,
                "error": code,
                "retryable": bool(failure.get("retryable", True)),
                "policy_caused": False,
            }
        return None

    def _policy_error(self, code: str, **extra: Any) -> dict[str, Any]:
        self.trace.policy_errors.append(code)
        return {"ok": False, "error": code, "policy_caused": True, **extra}

    def _can_read(self, document: dict[str, Any]) -> bool:
        scope = str(document.get("access_scope", "free"))
        if scope == "free":
            return True
        return scope in {"owner", "private"} and str(document.get("owner_id")) == str(self.identity.get("user_id"))

    def _knowledge_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = int(arguments.get("limit", 5))
        visible = [row for row in self._documents.values() if self._can_read(row)]
        hits = ReplayIndex(visible).search(str(arguments["query"]), limit=limit)
        results = []
        for score, row in hits:
            source_id = str(row["source_id"])
            self.trace.discovered_source_ids.add(source_id)
            results.append(
                {
                    "source_id": source_id,
                    "material_id": row.get("material_id"),
                    "title": row.get("title", ""),
                    "snippet": str(row.get("text", ""))[:320],
                    "score": score,
                    "citation": f"[{source_id}]",
                }
            )
        return {
            "ok": True,
            "query": arguments["query"],
            "results": results,
            "returned_source_ids": [row["source_id"] for row in results],
            "retrieval_backend": "bm25_mixed_zh_en_v1",
        }

    def _knowledge_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source_id = str(arguments["source_id"])
        document = self._documents.get(source_id)
        if document is None:
            return self._policy_error("source_not_found", source_id=source_id)
        if not self._can_read(document):
            self.trace.denied_source_ids.add(source_id)
            return {
                "ok": False,
                "error": "permission_denied",
                "source_id": source_id,
                "policy_caused": False,
                "recovery_hint": "Search for an ACL-authorized alternative; do not infer hidden content.",
            }
        self.trace.read_source_ids.add(source_id)
        self.trace.discovered_source_ids.add(source_id)
        return {
            "ok": True,
            "source_id": source_id,
            "material_id": document.get("material_id"),
            "title": document.get("title", ""),
            "text": document.get("text", ""),
            "citation": f"[{source_id}]",
            "returned_source_ids": [source_id],
        }

    def _knowledge_browse(self, arguments: dict[str, Any]) -> dict[str, Any]:
        material_id = int(arguments["material_id"])
        limit = int(arguments.get("limit", 5))
        rows = [
            row
            for row in self._documents.values()
            if int(row.get("material_id", -1)) == material_id and self._can_read(row)
        ][:limit]
        results = []
        for row in rows:
            source_id = str(row["source_id"])
            self.trace.discovered_source_ids.add(source_id)
            results.append(
                {
                    "source_id": source_id,
                    "title": row.get("title", ""),
                    "snippet": str(row.get("text", ""))[:320],
                    "citation": f"[{source_id}]",
                }
            )
        return {
            "ok": True,
            "material_id": material_id,
            "results": results,
            "returned_source_ids": [row["source_id"] for row in results],
        }

    def _web_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hits = self._web_index.search(str(arguments["query"]), limit=int(arguments.get("limit", 5)))
        results = []
        for score, row in hits:
            source_id = str(row["source_id"])
            self.trace.discovered_source_ids.add(source_id)
            results.append(
                {
                    "source_id": source_id,
                    "url": row["url"],
                    "title": row.get("title", ""),
                    "snippet": row.get("snippet", str(row.get("content", ""))[:320]),
                    "published_at": row.get("published_at"),
                    "source_quality": row.get("source_quality", "unknown"),
                    "score": score,
                    "citation": f"[{source_id}]",
                }
            )
        return {
            "ok": True,
            "query": arguments["query"],
            "results": results,
            "returned_source_ids": [row["source_id"] for row in results],
            "snapshot_at": self.environment.get("snapshot_at"),
        }

    def _web_fetch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = str(arguments["url"])
        page = self._web_pages.get(url)
        if page is None:
            return self._policy_error("url_not_in_replay_snapshot", url=url)
        source_id = str(page["source_id"])
        self.trace.discovered_source_ids.add(source_id)
        self.trace.read_source_ids.add(source_id)
        self.trace.fetched_urls.add(url)
        return {
            "ok": True,
            "source_id": source_id,
            "url": url,
            "title": page.get("title", ""),
            "content": page.get("content", ""),
            "published_at": page.get("published_at"),
            "source_quality": page.get("source_quality", "unknown"),
            "citation": f"[{source_id}]",
            "returned_source_ids": [source_id],
        }

    def _personal_memory_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        user_id = str(self.identity.get("user_id", ""))
        rows = [row for row in self._personal_memories if str(row.get("user_id")) == user_id]
        hits = ReplayIndex(rows).search(str(arguments["query"]), limit=int(arguments.get("limit", 5)))
        results = []
        for score, row in hits:
            source_id = str(row["source_id"])
            self.trace.discovered_source_ids.add(source_id)
            results.append(
                {
                    "source_id": source_id,
                    "content": row.get("content", ""),
                    "recorded_at": row.get("recorded_at"),
                    "valid_until": row.get("valid_until"),
                    "status": row.get("status", "current"),
                    "score": score,
                }
            )
        return {
            "ok": True,
            "memories": results,
            "returned_source_ids": [row["source_id"] for row in results],
        }

    def _collective_memory_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        course = str(arguments.get("course", "")).casefold()
        rows = [
            row for row in self._collective_memories if not course or course in str(row.get("course", "")).casefold()
        ]
        hits = ReplayIndex(rows).search(str(arguments["query"]), limit=int(arguments.get("limit", 5)))
        results = []
        for score, row in hits:
            source_id = str(row["source_id"])
            self.trace.discovered_source_ids.add(source_id)
            results.append(
                {
                    "source_id": source_id,
                    "course": row.get("course", ""),
                    "pattern": row.get("content", ""),
                    "sample_size": row.get("sample_size", 0),
                    "confidence": row.get("confidence", 0.0),
                    "score": score,
                }
            )
        return {
            "ok": True,
            "results": results,
            "privacy": "aggregate_only",
            "returned_source_ids": [row["source_id"] for row in results],
        }

    def _learning_profile_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        profile = dict(self.state.get("learning_profile", {}))
        for key in ("email", "phone", "real_name", "credentials"):
            profile.pop(key, None)
        return {"ok": True, "profile": profile}

    def _study_plan_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        authorized_materials = {
            int(row["material_id"])
            for row in self._documents.values()
            if row.get("material_id") is not None and self._can_read(row)
        }
        resource_ids = [int(value) for value in arguments["resource_ids"]]
        unauthorized = sorted(set(resource_ids) - authorized_materials)
        if unauthorized:
            return self._policy_error("unauthorized_resource", material_ids=unauthorized)
        item = {
            "topic": str(arguments["topic"]),
            "weekly_minutes": int(arguments["weekly_minutes"]),
            "resource_ids": resource_ids,
        }
        plans = self.state.setdefault("study_plans", {})
        plans[item["topic"]] = item
        self.trace.state_changes.append({"kind": "study_plan_updated", **item})
        return {"ok": True, "postcondition": "study_plan_saved", "plan": item}

    def _material_bookmark_add(self, arguments: dict[str, Any]) -> dict[str, Any]:
        material_id = int(arguments["material_id"])
        authorized = any(
            int(row.get("material_id", -1)) == material_id and self._can_read(row) for row in self._documents.values()
        )
        if not authorized:
            return self._policy_error("unauthorized_resource", material_id=material_id)
        bookmarks = self.state.setdefault("bookmarks", [])
        if material_id not in bookmarks:
            bookmarks.append(material_id)
        self.trace.state_changes.append({"kind": "bookmark_added", "material_id": material_id})
        return {"ok": True, "postcondition": "bookmark_present", "material_id": material_id}

    def _learning_progress_record(self, arguments: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "topic": str(arguments["topic"]),
            "status": str(arguments["status"]),
        }
        if "score" in arguments:
            entry["score"] = int(arguments["score"])
        progress = self.state.setdefault("progress", {})
        progress[entry["topic"]] = entry
        self.trace.state_changes.append({"kind": "progress_recorded", **entry})
        return {"ok": True, "postcondition": "progress_recorded", "progress": entry}

    def state_snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state, ensure_ascii=False))


@lru_cache(maxsize=8)
def _load_environment_store(path: str) -> dict[str, dict[str, Any]]:
    rows = load_jsonl(path)
    store: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = str(row["task_id"])
        if task_id in store:
            raise ValueError(f"duplicate environment task_id: {task_id}")
        store[task_id] = row
    return store


def _validate_arguments(schema: dict[str, Any], value: Any, *, path: str = "arguments") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    properties = schema.get("properties", {})
    unknown = set(value) - set(properties)
    if unknown and schema.get("additionalProperties") is False:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    missing = set(schema.get("required", [])) - set(value)
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")
    normalized = dict(value)
    for name, field_schema in properties.items():
        if name not in normalized and "default" in field_schema:
            normalized[name] = field_schema["default"]
        if name not in normalized:
            continue
        _validate_value(normalized[name], field_schema, path=f"{path}.{name}")
    return normalized


def _validate_value(value: Any, schema: dict[str, Any], *, path: str) -> None:
    kind = schema.get("type")
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        if not int(schema.get("minLength", 0)) <= len(value) <= int(schema.get("maxLength", 2**31)):
            raise ValueError(f"{path} has invalid length")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer")
        if not int(schema.get("minimum", -(2**31))) <= value <= int(schema.get("maximum", 2**31)):
            raise ValueError(f"{path} is out of range")
    elif kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        if len(value) > int(schema.get("maxItems", 2**31)):
            raise ValueError(f"{path} has too many items")
        for index, item in enumerate(value):
            _validate_value(item, schema.get("items", {}), path=f"{path}[{index}]")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
