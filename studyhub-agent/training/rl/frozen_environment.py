from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def canonical_arguments(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _terms(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", value.casefold())


@dataclass(slots=True)
class ExecutionTrace:
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    search_result_ids: set[str] = field(default_factory=set)
    read_source_ids: set[str] = field(default_factory=set)
    invalid_tool_calls: int = 0


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
            self.trace.invalid_tool_calls += 1
            return self._result(
                error="tool_call_budget_exhausted",
                max_tool_calls=self.max_tool_calls,
            )
        if tool is None:
            self.trace.invalid_tool_calls += 1
            return self._result(error="unknown_tool", tool=name)
        capability = tool.get("capability")
        if capability == "knowledge_search":
            return self._search(arguments)
        if capability == "knowledge_read":
            return self._read(arguments)
        if capability == "function_call":
            return self._fixture_call(name, arguments, tool)
        self.trace.invalid_tool_calls += 1
        return self._result(error="unsupported_capability", tool=name)

    def _search(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query", "")).strip()
        try:
            limit = max(1, min(8, int(arguments.get("limit", 5))))
        except (TypeError, ValueError):
            limit = 5
        if not query:
            self.trace.invalid_tool_calls += 1
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
                    "snippet": str(document.get("text", ""))[:500],
                }
            )
        return self._result(query=query, results=results)

    def _read(self, arguments: dict[str, Any]) -> str:
        source_id = str(arguments.get("source_id", "")).strip()
        document = self._documents.get(source_id)
        if document is None:
            self.trace.invalid_tool_calls += 1
            return self._result(error="source_not_found", source_id=source_id)
        self.trace.read_source_ids.add(source_id)
        return self._result(
            source_id=source_id,
            title=document.get("title", ""),
            text=document.get("text", ""),
            citation=f"[{source_id}]",
        )

    def _fixture_call(self, name: str, arguments: dict[str, Any], tool: dict[str, Any]) -> str:
        required = set(tool.get("parameters", {}).get("required", []))
        missing = sorted(required - arguments.keys())
        if missing:
            self.trace.invalid_tool_calls += 1
            return self._result(error="missing_required_arguments", missing=missing)
        route = self._routes.get((name, canonical_arguments(arguments)))
        if route is None:
            return self._result(ok=True, tool=name, arguments=arguments, fixture_match=False)
        return self._result(ok=True, tool=name, content=route, fixture_match=True)

    @staticmethod
    def _result(**value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
