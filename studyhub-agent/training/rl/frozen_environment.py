from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEARCH_SNIPPET_CHARS = 200


def canonical_arguments(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _terms(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", value.casefold())


def _nested_source_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        source_id = value.get("source_id")
        if isinstance(source_id, str) and source_id:
            result.add(source_id)
        for child in value.values():
            result.update(_nested_source_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_nested_source_ids(child))
    return result


@dataclass(slots=True)
class ExecutionTrace:
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    search_result_ids: set[str] = field(default_factory=set)
    read_source_ids: set[str] = field(default_factory=set)
    invalid_tool_calls: int = 0
    error_codes: list[str] = field(default_factory=list)
    runtime_errors: list[str] = field(default_factory=list)


class FrozenTaskEnvironment:
    """Execute only the fixture tools or frozen corpus declared for one RL task."""

    def __init__(
        self,
        environment: dict[str, Any],
        fixture: dict[str, Any] | None = None,
        *,
        max_tool_calls: int | None = None,
    ) -> None:
        self.environment = environment
        self.fixture = fixture or {}
        if max_tool_calls is not None and max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        self.max_tool_calls = max_tool_calls
        self.trace = ExecutionTrace()
        self._tools = {row["name"]: row for row in environment.get("tools", [])}
        self._documents = {row["source_id"]: row for row in environment.get("documents", [])}
        self._routes = {
            (row["name"], canonical_arguments(row["arguments"])): row.get("result")
            for row in self.fixture.get("routes", [])
        }
        self._routes_by_name: dict[str, list[dict[str, Any]]] = {}
        for row in self.fixture.get("routes", []):
            self._routes_by_name.setdefault(str(row["name"]), []).append(row)

    @classmethod
    def from_root(
        cls,
        root: str | Path,
        task_id: str,
        *,
        max_tool_calls: int | None = None,
    ) -> FrozenTaskEnvironment:
        root = Path(root)
        environment = json.loads((root / "environments" / f"{task_id}.json").read_text(encoding="utf-8"))
        fixture_path = root / "fixtures" / f"{task_id}.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8")) if fixture_path.is_file() else None
        return cls(environment, fixture, max_tool_calls=max_tool_calls)

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": row["name"],
                "description": row["description"],
                "parameters": row["parameters"],
            }
            for row in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        self.trace.tool_calls.append({"name": name, "arguments": dict(arguments)})
        if self.max_tool_calls is not None and len(self.trace.tool_calls) > self.max_tool_calls:
            self._record_error("tool_call_budget_exhausted")
            return self._result(
                error="tool_call_budget_exhausted",
                max_tool_calls=self.max_tool_calls,
            )
        if tool is None:
            self._record_error("unknown_tool")
            return self._result(error="unknown_tool", tool=name)
        capability = tool.get("capability")
        if capability == "knowledge_search":
            return self._search(arguments)
        if capability == "knowledge_read":
            return self._read(arguments)
        if capability == "replay_search":
            return self._replay_search(name, arguments)
        if capability in {"function_call", "evidence_fetch"}:
            return self._fixture_call(
                name,
                arguments,
                tool,
                records_evidence=capability == "evidence_fetch",
            )
        self._record_error("unsupported_capability")
        return self._result(error="unsupported_capability", tool=name)

    def record_runtime_error(self, code: str) -> None:
        if code not in self.trace.runtime_errors:
            self.trace.runtime_errors.append(code)

    def _search(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query", "")).strip()
        try:
            limit = max(1, min(8, int(arguments.get("limit", 5))))
        except (TypeError, ValueError):
            limit = 5
        if not query:
            self._record_error("query_required")
            return self._result(error="query_required")
        query_terms = _terms(query)
        scored = []
        for document in self._documents.values():
            title = str(document.get("title", ""))
            text = str(document.get("text", ""))
            title_terms = _terms(title)
            text_terms = _terms(text)
            score = 4 * sum(title_terms.count(term) for term in query_terms)
            score += sum(text_terms.count(term) for term in query_terms)
            if query.casefold() in f"{title} {text}".casefold():
                score += 20
            if score:
                scored.append((score, document["source_id"], document))
        scored.sort(key=lambda item: (-item[0], item[1]))
        results = []
        for score, source_id, document in scored[:limit]:
            self.trace.search_result_ids.add(source_id)
            results.append(
                {
                    "source_id": source_id,
                    "title": document.get("title", ""),
                    "score": score,
                    "snippet": str(document.get("text", ""))[:SEARCH_SNIPPET_CHARS],
                }
            )
        return self._result(query=query, results=results)

    def _read(self, arguments: dict[str, Any]) -> str:
        source_id = str(arguments.get("source_id", "")).strip()
        route_key = ("knowledge_read", canonical_arguments(arguments))
        if route_key in self._routes:
            return json.dumps(self._routes[route_key], ensure_ascii=False, sort_keys=True)
        document = self._documents.get(source_id)
        if document is None:
            self._record_error("source_not_found")
            return self._result(error="source_not_found", source_id=source_id)
        if source_id not in self.trace.search_result_ids:
            self._record_error("source_not_discovered")
            return self._result(error="source_not_discovered", source_id=source_id)
        self.trace.read_source_ids.add(source_id)
        return self._result(
            source_id=source_id,
            title=document.get("title", ""),
            text=document.get("text", ""),
            citation=f"[{source_id}]",
        )

    @staticmethod
    def _route_matches(arguments: dict[str, Any], route: dict[str, Any]) -> bool:
        match = route.get("argument_match")
        if not isinstance(match, dict) or match.get("mode") != "exact_except":
            return False
        expected = route.get("arguments", {})
        flexible = set(match.get("flexible_fields", []))
        if not isinstance(expected, dict) or not flexible <= expected.keys():
            return False
        for key, value in expected.items():
            if key in flexible:
                if key not in arguments or not isinstance(arguments[key], type(value)):
                    return False
                if isinstance(arguments[key], str) and not arguments[key].strip():
                    return False
                continue
            if arguments.get(key) != value:
                return False
        return set(arguments) == set(expected)

    def _fixture_call(
        self,
        name: str,
        arguments: dict[str, Any],
        tool: dict[str, Any],
        *,
        records_evidence: bool = False,
    ) -> str:
        required = set(tool.get("parameters", {}).get("required", []))
        missing = sorted(required - arguments.keys())
        if missing:
            self._record_error("missing_required_arguments")
            return self._result(error="missing_required_arguments", missing=missing)
        route_key = (name, canonical_arguments(arguments))
        route = self._routes.get(route_key)
        if route is None:
            route_row = next(
                (
                    candidate
                    for candidate in self._routes_by_name.get(name, [])
                    if self._route_matches(arguments, candidate)
                ),
                None,
            )
            route = route_row.get("result") if route_row is not None else None
        if route is None:
            self._record_error("fixture_route_not_found")
            return self._result(
                ok=False,
                error="fixture_route_not_found",
                tool=name,
                fixture_match=False,
            )
        if records_evidence:
            self.trace.read_source_ids.update(_nested_source_ids(route))
        return self._result(ok=True, tool=name, content=route, fixture_match=True)

    def _replay_search(self, name: str, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            self._record_error("query_required")
            return self._result(error="query_required", tool=name)
        routes = self._routes_by_name.get(name, [])
        if not routes:
            self._record_error("replay_search_route_missing")
            return self._result(error="replay_search_route_missing", tool=name)
        query_terms = _terms(query)
        scored = []
        for ordinal, route in enumerate(routes):
            searchable = (
                f"{canonical_arguments(route.get('arguments', {}))} {canonical_arguments(route.get('result', {}))}"
            )
            searchable_terms = _terms(searchable)
            score = sum(searchable_terms.count(term) for term in query_terms)
            scored.append((score, -ordinal, route))
        _score, _ordinal, selected = max(scored, key=lambda item: (item[0], item[1]))
        result = selected.get("result")
        if isinstance(result, dict):
            result = dict(result)
            if "query" in result:
                result["query"] = query
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def _record_error(self, code: str) -> None:
        self.trace.invalid_tool_calls += 1
        self.trace.error_codes.append(code)

    @staticmethod
    def _result(**value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
