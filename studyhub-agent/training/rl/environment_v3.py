from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.environment import ReplayableAgentEnvironmentV2
from studyhub_agent.benchmark_v2.schema import BENCHMARK_VERSION, ENVIRONMENT_SCHEMA_VERSION

ENVIRONMENT_V3_SCHEMA = "studyhub.rl-environment.v3"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> None:
    kind = schema.get("type")
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        if len(value) < int(schema.get("minLength", 0)) or len(value) > int(schema.get("maxLength", 2**31)):
            raise ValueError(f"{path} has invalid length")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer")
        if value < int(schema.get("minimum", -(2**31))) or value > int(schema.get("maximum", 2**31)):
            raise ValueError(f"{path} is out of range")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} must be a number")
    elif kind == "boolean" and not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    elif kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        if len(value) > int(schema.get("maxItems", 2**31)):
            raise ValueError(f"{path} has too many items")
        for index, item in enumerate(value):
            _validate_value(item, schema.get("items", {}), f"{path}[{index}]")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")


def _validate_arguments(schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    properties = dict(schema.get("properties", {}))
    unknown = set(arguments) - set(properties)
    if unknown and schema.get("additionalProperties") is False:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    missing = set(schema.get("required", [])) - set(arguments)
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    normalized = dict(arguments)
    for name, field_schema in properties.items():
        if name not in normalized and "default" in field_schema:
            normalized[name] = field_schema["default"]
        if name in normalized:
            _validate_value(normalized[name], field_schema, f"arguments.{name}")
    return normalized


def _merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_patch(target[key], value)
        else:
            target[key] = json.loads(json.dumps(value, ensure_ascii=False))


@dataclass(slots=True)
class FixtureTrace:
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


class FixtureEnvironmentV3:
    """Execute arbitrary open-source tool schemas against deterministic routes."""

    def __init__(self, environment: dict[str, Any]) -> None:
        self.environment = environment
        self.task_id = str(environment["task_id"])
        self.trace = FixtureTrace()
        self.state = json.loads(json.dumps(environment.get("initial_state", {}), ensure_ascii=False))
        self._max_tool_calls = int(environment.get("max_tool_calls", 8))
        self._schemas = {str(row["name"]): dict(row) for row in environment.get("tool_schemas", [])}
        self._routes: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in environment.get("fixture_routes", []):
            name = str(row["name"])
            schema = self._schemas.get(name, {})
            normalized = _validate_arguments(schema.get("parameters", {}), row.get("arguments", {}))
            key = (name, _canonical(normalized))
            self._routes.setdefault(key, []).append(dict(row))
        self._route_occurrences: dict[tuple[str, str], int] = {}

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": row["name"],
                "description": row.get("description", row["name"]),
                "parameters": row.get("parameters", {"type": "object", "properties": {}}),
            }
            for row in self._schemas.values()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        call: dict[str, Any] = {
            "index": len(self.trace.tool_calls),
            "name": name,
            "arguments": dict(arguments) if isinstance(arguments, dict) else {},
        }
        self.trace.tool_calls.append(call)
        if len(self.trace.tool_calls) > self._max_tool_calls:
            return self._finish(call, self._policy_error("tool_call_budget_exhausted"))
        schema = self._schemas.get(name)
        if schema is None:
            return self._finish(call, self._policy_error("unknown_tool", tool=name))
        try:
            normalized = _validate_arguments(schema.get("parameters", {}), arguments)
        except ValueError as error:
            return self._finish(call, self._policy_error("invalid_arguments", detail=str(error)))
        call["arguments"] = normalized
        key = (name, _canonical(normalized))
        routes = self._routes.get(key, [])
        occurrence = self._route_occurrences.get(key, 0)
        self._route_occurrences[key] = occurrence + 1
        if not routes:
            return self._finish(call, self._policy_error("fixture_route_not_found", tool=name))
        route = routes[min(occurrence, len(routes) - 1)]
        result = json.loads(json.dumps(route.get("result", {"ok": True}), ensure_ascii=False))
        if not isinstance(result, dict):
            result = {"ok": True, "content": result}
        result.setdefault("ok", True)
        state_patch = route.get("state_patch")
        if result.get("ok") and isinstance(state_patch, dict):
            _merge_patch(self.state, state_patch)
            change = {"kind": "fixture_state_patch", "tool": name, "patch": state_patch}
            self.trace.state_changes.append(change)
        if not result.get("ok"):
            code = str(result.get("error", "fixture_failure"))
            if result.get("policy_caused"):
                self.trace.policy_errors.append(code)
            else:
                self.trace.environment_errors.append(code)
        return self._finish(call, result)

    def _policy_error(self, code: str, **extra: Any) -> dict[str, Any]:
        self.trace.policy_errors.append(code)
        return {"ok": False, "error": code, "policy_caused": True, **extra}

    def _finish(self, call: dict[str, Any], result: dict[str, Any]) -> str:
        returned = list(map(str, result.get("returned_source_ids", [])))
        call.update(
            {
                "ok": bool(result.get("ok", False)),
                "error": result.get("error"),
                "returned_source_ids": returned,
                "observation": result,
            }
        )
        self.trace.discovered_source_ids.update(returned)
        if result.get("source_id") and result.get("ok"):
            source_id = str(result["source_id"])
            self.trace.read_source_ids.add(source_id)
            self.trace.discovered_source_ids.add(source_id)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def state_snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state, ensure_ascii=False))

    def record_runtime_error(self, code: str) -> None:
        if code not in self.trace.runtime_errors:
            self.trace.runtime_errors.append(code)


class TrainingReplayEnvironmentV3(ReplayableAgentEnvironmentV2):
    """Tighten the training Web contract without changing frozen Benchmark v2."""

    def _web_fetch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        page = self._web_pages.get(str(arguments["url"]))
        if page is not None and str(page["source_id"]) not in self.trace.discovered_source_ids:
            return self._policy_error("url_not_discovered", url=str(arguments["url"]))
        return super()._web_fetch(arguments)


class TrainingTaskEnvironmentV3:
    """Training-only adapter over replay or arbitrary fixture environments."""

    def __init__(self, environment: dict[str, Any], *, root: Path) -> None:
        if environment.get("schema_version") != ENVIRONMENT_V3_SCHEMA:
            raise ValueError(f"unsupported training environment: {environment.get('schema_version')}")
        self.environment = environment
        kind = str(environment.get("environment_kind", "replay"))
        if kind == "fixture":
            self._inner: Any = FixtureEnvironmentV3(environment)
        elif kind == "replay":
            compatibility = dict(environment)
            compatibility["schema_version"] = ENVIRONMENT_SCHEMA_VERSION
            compatibility["benchmark_version"] = BENCHMARK_VERSION
            compatibility.setdefault("split", "training")
            self._inner = TrainingReplayEnvironmentV3(compatibility, root=root)
        else:
            raise ValueError(f"unsupported environment_kind: {kind}")

    @classmethod
    def from_root(cls, root: str | Path, task_id: str) -> TrainingTaskEnvironmentV3:
        root_path = Path(root).resolve()
        path = root_path / "environments" / f"{task_id}.json"
        environment = json.loads(path.read_text(encoding="utf-8"))
        if str(environment.get("task_id")) != task_id:
            raise ValueError(f"environment task mismatch: {task_id}")
        return cls(environment, root=root_path)

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return self._inner.tool_schemas

    @property
    def mutating_tools(self) -> set[str]:
        return set(map(str, self.environment.get("mutating_tools", [])))

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        return await self._inner.execute(name, arguments)

    def record_runtime_error(self, code: str) -> None:
        self._inner.record_runtime_error(code)

    def trace_dict(self) -> dict[str, Any]:
        return self._inner.trace.to_dict()

    def state_snapshot(self) -> dict[str, Any]:
        return self._inner.state_snapshot()
