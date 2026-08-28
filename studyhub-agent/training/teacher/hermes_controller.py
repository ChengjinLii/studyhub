from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from studyhub_agent.integrations.hermes_registry import HermesRegistryOverlay
from training.rl.frozen_environment import FrozenTaskEnvironment
from training.teacher.providers import _visible_runtime_state

ActionChooser = Callable[
    [dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int],
    tuple[dict[str, Any], dict[str, Any]],
]

SYSTEM_PROMPT = """You are StudyHub Agent in an isolated teacher-data environment.
Choose exactly one visible action each turn. Use only the supplied tools. Never access
the filesystem, shell, network, credentials, benchmark graders, or private sources.
Use actual observations, cite read/fetched sources, and stop when the answer is supported.
Do not provide hidden chain-of-thought."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_hermes_registry(checkout: Path, expected_commit: str) -> Any:
    checkout = checkout.resolve()
    actual = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual != expected_commit:
        raise RuntimeError(f"Hermes checkout drift: expected={expected_commit}, actual={actual}")
    if str(checkout) not in sys.path:
        sys.path.insert(0, str(checkout))
    from tools.registry import registry

    return registry


def _openai_tools(environment: FrozenTaskEnvironment) -> list[dict[str, Any]]:
    return [{"type": "function", "function": schema} for schema in environment.tool_schemas]


def _validate_action(action: dict[str, Any]) -> list[str]:
    failures = []
    if action.get("type") not in {"tool_call", "final"}:
        failures.append("invalid_action_type")
    if action.get("type") == "tool_call":
        if not str(action.get("name", "")):
            failures.append("missing_tool_name")
        if not isinstance(action.get("arguments"), dict):
            failures.append("arguments_not_object")
    if action.get("type") == "final" and not str(action.get("content", "")).strip():
        failures.append("empty_final")
    return failures


def collect_trajectory(
    *,
    task: dict[str, Any],
    root: Path,
    hermes_checkout: Path,
    hermes_commit: str,
    choose_action: ActionChooser,
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    environment = FrozenTaskEnvironment.from_root(root, task_id, max_tool_calls=int(task["max_tool_calls"]))
    registry = load_hermes_registry(hermes_checkout, hermes_commit)
    overlay = HermesRegistryOverlay(registry)
    toolset = f"studyhub-teacher-{task_id}"
    tool_map = {schema["name"]: schema for schema in environment.tool_schemas}
    tools = _openai_tools(environment)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": str(task["user_request"])},
    ]
    provider_events: list[dict[str, Any]] = []
    controller_errors: list[str] = []
    policy_corrections: list[dict[str, Any]] = []
    final_answer = ""

    for schema in environment.tool_schemas:
        name = schema["name"]

        async def handler(arguments: dict[str, Any], _name: str = name, **_kwargs: Any) -> str:
            return await environment.execute(_name, arguments)

        overlay.install(name=name, toolset=toolset, schema=schema, handler=handler)

    try:
        for turn in range(int(task["max_steps"])):
            action, provider_event = choose_action(task, tools, list(messages), turn)
            provider_events.append(provider_event)
            failures = _validate_action(action)
            if failures:
                controller_errors.extend(failures)
                break
            if action["type"] == "final":
                runtime_state = _visible_runtime_state(task, messages, turn + 1)
                if not runtime_state["final_ready"]:
                    correction = {
                        "turn": turn,
                        "reason": "premature_final",
                        "grounded_citation_deficit": runtime_state["grounded_citation_deficit"],
                        "successful_state_change_deficit": runtime_state["successful_state_change_deficit"],
                        "remaining_model_steps": runtime_state["remaining_model_steps"],
                        "remaining_tool_calls": runtime_state["remaining_tool_calls"],
                    }
                    policy_corrections.append(correction)
                    if not runtime_state["remaining_model_steps"] or not runtime_state["remaining_tool_calls"]:
                        controller_errors.append("premature_final_without_recovery_budget")
                        break
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "<runtime_feedback>Final action not accepted: public completion constraints "
                                f"remain unmet (grounded_citation_deficit="
                                f"{runtime_state['grounded_citation_deficit']}, successful_state_change_deficit="
                                f"{runtime_state['successful_state_change_deficit']}). Continue with one allowed "
                                "tool action using only visible observations.</runtime_feedback>"
                            ),
                        }
                    )
                    continue
                final_answer = str(action["content"]).strip()
                messages.append({"role": "assistant", "content": final_answer})
                break

            name = str(action["name"])
            arguments = dict(action["arguments"])
            schema = tool_map.get(name)
            if schema is None:
                controller_errors.append("unknown_tool")
                break
            validation_errors = sorted(
                Draft202012Validator(schema["parameters"]).iter_errors(arguments),
                key=lambda error: list(error.path),
            )
            if validation_errors:
                controller_errors.append("schema_validation_failed")
                break
            call_key = f"{task_id}:{turn}:{name}:{json.dumps(arguments, sort_keys=True)}"
            call_id = f"call_{hashlib.sha256(call_key.encode()).hexdigest()[:20]}"
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                }
            )
            observation = registry.dispatch(name, arguments, task_id=task_id)
            messages.append(
                {
                    "role": "tool",
                    "name": name,
                    "tool_call_id": call_id,
                    "content": observation,
                }
            )
        else:
            controller_errors.append("max_steps_without_final")
    finally:
        overlay.restore()

    path_signature = "→".join(row["name"] for row in environment.trace.tool_calls) or "DIRECT"
    return {
        "schema_version": "studyhub.teacher-raw-run.v2",
        "task_id": task_id,
        "task_spec_sha256": hashlib.sha256(json.dumps(task, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "source": dict(task.get("metadata", {})),
        "family": task.get("family"),
        "tools": tools,
        "messages": messages,
        "final_answer": final_answer,
        "path_signature": path_signature,
        "controller": {
            "hermes_registry_dispatch": True,
            "hermes_commit": hermes_commit,
            "environment_sha256": sha256(root / "environments" / f"{task_id}.json"),
            "fixture_sha256": sha256(root / "fixtures" / f"{task_id}.json"),
            "tool_calls": len(environment.trace.tool_calls),
            "invalid_tool_calls": environment.trace.invalid_tool_calls,
            "environment_errors": list(environment.trace.error_codes),
            "runtime_errors": list(environment.trace.runtime_errors),
            "controller_errors": controller_errors,
            "policy_corrections": policy_corrections,
            "read_source_ids": sorted(environment.trace.read_source_ids),
            "search_result_ids": sorted(environment.trace.search_result_ids),
        },
        "provider_events": provider_events,
        "status": "COMPLETED" if final_answer and not controller_errors else "FAILED",
    }
