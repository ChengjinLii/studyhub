from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ACTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ["tool_call", "final"]},
        "name": {"type": "string"},
        "arguments": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["type", "name", "arguments", "content"],
}

LOCAL_ACTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ["tool_call", "final"]},
        "name": {"type": "string"},
        "arguments": {"type": "object"},
        "content": {"type": "string"},
    },
    "required": ["type", "name", "arguments", "content"],
}

PROVIDER_SYSTEM = """You are the policy teacher for one isolated StudyHub Agent turn.
Return exactly one JSON action matching the supplied schema. Do not use a shell, filesystem,
network, browser, or any tool of your own. The only permitted actions are one listed StudyHub
tool call or a final answer. Base the action only on the public task and visible message history.
For evidence tasks, a search result only discovers a source: read or fetch every source before
citing it. Never invent a source ID or infer a fetch URL that was not returned by an observation.
Write final citations exactly as [source_id], using only source IDs returned by a successful
read/fetch observation. Do not finish while a public completion constraint is visibly unmet.
If a tool returns an error, correct the next visible action instead of claiming success. Do not
reveal chain-of-thought."""

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\btp-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~-]{12,}"),
)


class TeacherProviderError(RuntimeError):
    def __init__(self, code: str, event: dict[str, Any]) -> None:
        super().__init__(code)
        self.code = code
        self.event = event


class ActionProvider(Protocol):
    interface: str
    model: str

    def availability(self) -> dict[str, Any]: ...

    def choose_action(
        self,
        task: dict[str, Any],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        turn: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _redact(value: str, *, limit: int = 800) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result[:limit]


def _json_payload(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _source_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        source_id = value.get("source_id")
        if isinstance(source_id, str) and source_id:
            result.add(source_id)
        for child in value.values():
            result.update(_source_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_source_ids(child))
    return result


def _nested_strings(value: Any, key: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        item = value.get(key)
        if isinstance(item, str) and item:
            result.add(item)
        for child in value.values():
            result.update(_nested_strings(child, key))
    elif isinstance(value, list):
        for child in value:
            result.update(_nested_strings(child, key))
    return result


def _visible_runtime_state(
    task: dict[str, Any],
    messages: list[dict[str, Any]],
    turn: int,
) -> dict[str, Any]:
    completed_tools: list[str] = []
    discovered: set[str] = set()
    grounded: set[str] = set()
    state_postconditions: set[str] = set()
    tool_calls = 0
    last_tool_error: str | None = None
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls", []):
                name = str(call.get("function", {}).get("name", ""))
                if name:
                    completed_tools.append(name)
                    tool_calls += 1
            continue
        if message.get("role") != "tool":
            continue
        name = str(message.get("name", ""))
        payload = _json_payload(message.get("content", ""))
        ids = _source_ids(payload)
        if name.endswith("_search") or name == "knowledge_search":
            discovered.update(ids)
        if name.endswith("_read") or name.endswith("_fetch") or name == "knowledge_read":
            grounded.update(ids)
        if isinstance(payload, dict):
            errors = _nested_strings(payload, "error")
            if payload.get("ok") is True and not errors:
                state_postconditions.update(_nested_strings(payload, "postcondition"))
            if errors:
                last_tool_error = sorted(errors)[-1]

    contract = task.get("completion_contract", {})
    minimum_citations = int(contract.get("minimum_grounded_citations", 0))
    minimum_state_changes = int(contract.get("minimum_successful_state_changes", 0))
    return {
        "completed_tool_calls": completed_tools,
        "discovered_source_ids": sorted(discovered),
        "grounded_source_ids": sorted(grounded),
        "minimum_grounded_citations": minimum_citations,
        "grounded_citation_deficit": max(0, minimum_citations - len(grounded)),
        "successful_state_postconditions": sorted(state_postconditions),
        "minimum_successful_state_changes": minimum_state_changes,
        "successful_state_change_deficit": max(0, minimum_state_changes - len(state_postconditions)),
        "remaining_model_steps": max(0, int(task.get("max_steps", 0)) - turn),
        "remaining_tool_calls": max(0, int(task.get("max_tool_calls", 0)) - tool_calls),
        "last_tool_error": last_tool_error,
        "final_evidence_ready": len(grounded) >= minimum_citations,
        "final_state_ready": len(state_postconditions) >= minimum_state_changes,
        "final_ready": len(grounded) >= minimum_citations and len(state_postconditions) >= minimum_state_changes,
    }


def _action_prompt(
    task: dict[str, Any],
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    turn: int,
    *,
    arguments_as_object: bool = False,
) -> str:
    payload = {
        "instruction": PROVIDER_SYSTEM,
        "turn": turn,
        "public_task": task,
        "studyhub_tools": tools,
        "visible_messages": messages,
        "visible_runtime_state": _visible_runtime_state(task, messages, turn),
        "action_contract": {
            "tool_call": {
                "type": "tool_call",
                "name": "tool name",
                "arguments": (
                    {"tool_parameter": "value"} if arguments_as_object else "JSON object encoded as a string"
                ),
                "content": "",
            },
            "final": {
                "type": "final",
                "name": "",
                "arguments": {} if arguments_as_object else "{}",
                "content": "supported answer",
            },
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _parse_action(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        action = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TeacherProviderError(
            "provider_output_not_json",
            {
                "error": "provider_output_not_json",
                "output_sha256": _sha256_text(value),
                "output_excerpt": _redact(value),
            },
        ) from exc
    if not isinstance(action, dict):
        raise TeacherProviderError(
            "provider_output_not_object",
            {
                "error": "provider_output_not_object",
                "output_sha256": _sha256_text(value),
                "output_excerpt": _redact(value),
            },
        )
    if action.get("type") == "final":
        action["arguments"] = {}
        return action
    arguments = action.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise TeacherProviderError(
                "provider_arguments_not_json",
                {
                    "error": "provider_arguments_not_json",
                    "output_sha256": _sha256_text(value),
                    "output_excerpt": _redact(value),
                },
            ) from exc
    if not isinstance(arguments, dict):
        raise TeacherProviderError(
            "provider_arguments_not_object",
            {
                "error": "provider_arguments_not_object",
                "output_sha256": _sha256_text(value),
                "output_excerpt": _redact(value),
            },
        )
    action["arguments"] = arguments
    return action


def _parse_action_with_event(value: str, event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return _parse_action(value), event
    except TeacherProviderError as exc:
        raise TeacherProviderError(exc.code, {**event, **exc.event}) from exc


def _chat_action_output(payload: dict[str, Any]) -> tuple[str, str]:
    choice = payload.get("choices", [{}])[0]
    message = choice.get("message", {}) if isinstance(choice, dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str) and content.strip():
        return content, "content"
    tool_calls = message.get("tool_calls", []) if isinstance(message, dict) else []
    if isinstance(tool_calls, list) and len(tool_calls) == 1 and isinstance(tool_calls[0], dict):
        function = tool_calls[0].get("function", {})
        if isinstance(function, dict) and function.get("name"):
            return (
                json.dumps(
                    {
                        "type": "tool_call",
                        "name": str(function["name"]),
                        "arguments": function.get("arguments", "{}"),
                        "content": "",
                    },
                    ensure_ascii=False,
                ),
                "tool_calls",
            )
    reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
    if isinstance(reasoning, str) and reasoning.lstrip().startswith("{") and reasoning.rstrip().endswith("}"):
        return reasoning, "reasoning_json"
    return "", "empty"


def _codex_event_audit(stdout: str) -> dict[str, Any]:
    event_types: dict[str, int] = {}
    item_types: dict[str, int] = {}
    forbidden_items: list[str] = []
    malformed = 0
    usage: dict[str, Any] = {}
    errors: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        event_type = str(event.get("type", "unknown"))
        event_types[event_type] = event_types.get(event_type, 0) + 1
        if event_type in {"error", "turn.failed"}:
            detail = event.get("message") or event.get("error") or event
            errors.append(_redact(json.dumps(detail, ensure_ascii=False, sort_keys=True), limit=500))
        item = event.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type", "unknown"))
            item_types[item_type] = item_types.get(item_type, 0) + 1
            if item_type not in {"reasoning", "agent_message"}:
                forbidden_items.append(item_type)
        if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = dict(event["usage"])
    return {
        "event_types": dict(sorted(event_types.items())),
        "item_types": dict(sorted(item_types.items())),
        "malformed_event_lines": malformed,
        "forbidden_item_types": sorted(set(forbidden_items)),
        "zero_codex_tool_events": not forbidden_items,
        "usage": usage,
        "errors": errors,
    }


@dataclass(slots=True)
class CodexSparkProvider:
    model: str = "gpt-5.3-codex-spark"
    timeout_seconds: int = 300
    command: str = "codex"
    interface: str = "codex-spark-cli"

    def availability(self) -> dict[str, Any]:
        executable = shutil.which(self.command)
        if not executable:
            return {"available": False, "reason": "codex_cli_not_found", "model": self.model}
        version = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return {
            "available": version.returncode == 0,
            "reason": "probe_required" if version.returncode == 0 else "codex_version_failed",
            "model": self.model,
            "cli_version": _redact(version.stdout.strip()),
            "isolation_policy": "temporary_public_dir_and_reject_any_codex_tool_event",
        }

    def choose_action(
        self,
        task: dict[str, Any],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        turn: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prompt = _action_prompt(task, tools, messages, turn)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="studyhub-teacher-public-") as directory:
            root = Path(directory)
            schema_path = root / "action-schema.json"
            output_path = root / "action.json"
            public_path = root / "public-task.json"
            schema_path.write_text(json.dumps(ACTION_SCHEMA, sort_keys=True), encoding="utf-8")
            public_path.write_text(json.dumps(task, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            command = [
                self.command,
                "--ask-for-approval",
                "never",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--model",
                self.model,
                "--cd",
                str(root),
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--json",
                "-",
            ]
            try:
                process = subprocess.run(
                    command,
                    input=prompt,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env={**os.environ, "NO_COLOR": "1"},
                )
            except subprocess.TimeoutExpired as exc:
                raise TeacherProviderError(
                    "codex_timeout",
                    {
                        "interface": self.interface,
                        "model": self.model,
                        "duration_seconds": round(time.monotonic() - started, 3),
                        "prompt_sha256": _sha256_text(prompt),
                    },
                ) from exc
            audit = _codex_event_audit(process.stdout)
            event = {
                "interface": self.interface,
                "model": self.model,
                "duration_seconds": round(time.monotonic() - started, 3),
                "exit_code": process.returncode,
                "prompt_sha256": _sha256_text(prompt),
                "stdout_sha256": _sha256_text(process.stdout),
                "stderr_sha256": _sha256_text(process.stderr),
                "stderr_excerpt": _redact(process.stderr),
                "sandbox": "read-only",
                "public_files": ["action-schema.json", "public-task.json"],
                "hidden_oracle_mounted": False,
                "event_audit": audit,
                "usage": audit["usage"],
            }
            if process.returncode != 0:
                error_text = " ".join(audit.get("errors", [])).casefold()
                if "usage limit" in error_text:
                    code = "codex_usage_limit"
                elif "rate limit" in error_text or "too many requests" in error_text:
                    code = "codex_rate_limit"
                else:
                    code = "codex_exec_failed"
                raise TeacherProviderError(code, event)
            if not audit["zero_codex_tool_events"]:
                raise TeacherProviderError("codex_isolation_tool_event", event)
            if not output_path.is_file():
                raise TeacherProviderError("codex_output_missing", event)
            output = output_path.read_text(encoding="utf-8")
            event["output_sha256"] = _sha256_text(output)
            return _parse_action_with_event(output, event)


def _response_output_text(payload: dict[str, Any]) -> str:
    value = payload.get("output_text")
    if isinstance(value, str) and value:
        return value
    texts = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                texts.append(str(content.get("text", "")))
    return "".join(texts)


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        raise TeacherProviderError(
            "teacher_http_error",
            {"status": exc.code, "body_excerpt": _redact(error_body), "body_sha256": _sha256_text(error_body)},
        ) from exc
    except urllib.error.URLError as exc:
        raise TeacherProviderError(
            "teacher_connection_error",
            {"reason": _redact(str(exc.reason))},
        ) from exc


@dataclass(slots=True)
class ResponsesAPIProvider:
    model: str = "gpt-5.3-codex"
    timeout_seconds: int = 180
    base_url: str = "https://api.openai.com/v1"
    interface: str = "openai-responses-api"

    def availability(self) -> dict[str, Any]:
        return {
            "available": bool(os.getenv("OPENAI_API_KEY")),
            "reason": "configured" if os.getenv("OPENAI_API_KEY") else "OPENAI_API_KEY_missing",
            "model": self.model,
        }

    def choose_action(
        self,
        task: dict[str, Any],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        turn: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise TeacherProviderError("responses_api_not_configured", self.availability())
        prompt = _action_prompt(task, tools, messages, turn)
        body = {
            "model": self.model,
            "input": prompt,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "studyhub_teacher_action",
                    "strict": True,
                    "schema": ACTION_SCHEMA,
                }
            },
        }
        started = time.monotonic()
        payload = _post_json(
            f"{self.base_url.rstrip('/')}/responses",
            body,
            {"Authorization": f"Bearer {api_key}"},
            self.timeout_seconds,
        )
        output = _response_output_text(payload)
        event = {
            "interface": self.interface,
            "model": payload.get("model", self.model),
            "response_id": payload.get("id"),
            "status": payload.get("status"),
            "duration_seconds": round(time.monotonic() - started, 3),
            "prompt_sha256": _sha256_text(prompt),
            "output_sha256": _sha256_text(output),
            "usage": payload.get("usage", {}),
            "store": False,
            "provider_tools": [],
            "hidden_oracle_available": False,
        }
        if payload.get("status") not in {None, "completed"}:
            raise TeacherProviderError("responses_api_incomplete", event)
        return _parse_action_with_event(output, event)


@dataclass(slots=True)
class LocalOpenAIProvider:
    model: str
    base_url: str
    api_key_env: str = "STUDYHUB_LOCAL_TEACHER_API_KEY"
    timeout_seconds: int = 180
    interface: str = "local-best-of-n"
    strict_json_schema: bool = True
    require_api_key: bool = False
    max_completion_tokens: int = 1024
    chat_template_kwargs: dict[str, Any] | None = None

    def availability(self) -> dict[str, Any]:
        configured = bool(self.base_url and self.model)
        key_available = bool(os.getenv(self.api_key_env))
        available = configured and (key_available or not self.require_api_key)
        return {
            "available": available,
            "reason": (
                "configured"
                if available
                else "api_key_missing"
                if configured and self.require_api_key
                else "endpoint_or_model_missing"
            ),
            "model": self.model,
            "base_url_sha256": _sha256_text(self.base_url) if self.base_url else None,
        }

    def choose_action(
        self,
        task: dict[str, Any],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        turn: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.base_url or not self.model:
            raise TeacherProviderError("local_teacher_not_configured", self.availability())
        prompt = _action_prompt(task, tools, messages, turn, arguments_as_object=True)
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_completion_tokens": self.max_completion_tokens,
            "response_format": (
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "studyhub_teacher_action",
                        "strict": True,
                        "schema": LOCAL_ACTION_SCHEMA,
                    },
                }
                if self.strict_json_schema
                else {"type": "json_object"}
            ),
        }
        if self.chat_template_kwargs is not None:
            body["chat_template_kwargs"] = self.chat_template_kwargs
        headers = {}
        api_key = os.getenv(self.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        started = time.monotonic()
        payload = _post_json(
            f"{self.base_url.rstrip('/')}/chat/completions",
            body,
            headers,
            self.timeout_seconds,
        )
        output, response_mode = _chat_action_output(payload)
        choice = payload.get("choices", [{}])[0]
        event = {
            "interface": self.interface,
            "model": payload.get("model", self.model),
            "response_id": payload.get("id"),
            "duration_seconds": round(time.monotonic() - started, 3),
            "prompt_sha256": _sha256_text(prompt),
            "output_sha256": _sha256_text(output),
            "usage": payload.get("usage", {}),
            "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None,
            "response_mode": response_mode,
            "provider_tools": [],
            "hidden_oracle_available": False,
        }
        return _parse_action_with_event(output, event)


def build_provider(
    teacher: str,
    *,
    model: str | None = None,
    timeout_seconds: int = 300,
) -> ActionProvider:
    if teacher == "codex-spark":
        return CodexSparkProvider(model=model or "gpt-5.3-codex-spark", timeout_seconds=timeout_seconds)
    if teacher == "responses-api":
        return ResponsesAPIProvider(
            model=model or os.getenv("STUDYHUB_RESPONSES_TEACHER_MODEL", "gpt-5.3-codex"),
            timeout_seconds=timeout_seconds,
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    if teacher == "local-best-of-n":
        return LocalOpenAIProvider(
            model=model or os.getenv("STUDYHUB_LOCAL_TEACHER_MODEL", ""),
            base_url=os.getenv("STUDYHUB_LOCAL_TEACHER_BASE_URL", ""),
            timeout_seconds=timeout_seconds,
            chat_template_kwargs={"enable_thinking": False},
        )
    if teacher == "authorized-openai-compatible":
        return LocalOpenAIProvider(
            model=model or os.getenv("STUDYHUB_COMPAT_TEACHER_MODEL", ""),
            base_url=os.getenv("STUDYHUB_COMPAT_TEACHER_BASE_URL", ""),
            api_key_env="STUDYHUB_COMPAT_TEACHER_API_KEY",
            timeout_seconds=timeout_seconds,
            interface="authorized-openai-compatible",
            strict_json_schema=False,
            require_api_key=True,
        )
    raise ValueError(f"unsupported teacher: {teacher}")
