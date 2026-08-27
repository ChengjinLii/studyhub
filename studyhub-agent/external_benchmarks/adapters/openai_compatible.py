"""OpenAI-compatible policy transport used by official benchmark harnesses.

The adapter does not implement a tool loop or evaluator. Each benchmark remains
responsible for its official task environment, orchestration, and scoring.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from external_benchmarks.result_schema import (
    GenerationRequest,
    GenerationResult,
    ModelEndpointConfig,
    ToolTrace,
    Usage,
)

Transport = Callable[[str, bytes, dict[str, str], float], dict[str, Any]]


def _default_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url=url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"model endpoint returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"model endpoint connection failed: {error.reason}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("model endpoint returned a non-object JSON payload")
    return payload


class OpenAICompatiblePolicyAdapter:
    """Serialize a policy request and parse one OpenAI chat-completion response."""

    adapter_revision = "studyhub-openai-compatible-v1"

    def __init__(self, config: ModelEndpointConfig, *, transport: Transport | None = None) -> None:
        self.config = config
        self._transport = transport or _default_transport

    def serialize(self, request: GenerationRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [dict(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = [dict(tool) for tool in request.tools]
            payload["tool_choice"] = "auto"
        if request.seed is not None:
            payload["seed"] = request.seed
        return payload

    def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing model endpoint credential in {self.config.api_key_env}")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self.config.organization_env and os.environ.get(self.config.organization_env):
            headers["OpenAI-Organization"] = os.environ[self.config.organization_env]
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = self._transport(
            endpoint,
            json.dumps(self.serialize(request), ensure_ascii=False).encode("utf-8"),
            headers,
            self.config.timeout_seconds,
        )
        return self.parse(payload)

    @staticmethod
    def parse(payload: dict[str, Any]) -> GenerationResult:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("chat completion response has no choices")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("chat completion choice has no message")
        traces = []
        for row in message.get("tool_calls") or []:
            if not isinstance(row, dict) or not isinstance(row.get("function"), dict):
                raise ValueError("invalid tool call payload")
            function = row["function"]
            arguments = function.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError as error:
                    raise ValueError("tool-call arguments are not valid JSON") from error
            if not isinstance(arguments, dict):
                raise ValueError("tool-call arguments must decode to an object")
            traces.append(
                ToolTrace(
                    tool_call_id=str(row.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )
        usage_payload = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        usage = Usage(
            prompt_tokens=int(usage_payload.get("prompt_tokens") or 0),
            completion_tokens=int(usage_payload.get("completion_tokens") or 0),
            total_tokens=int(usage_payload.get("total_tokens") or 0),
        )
        content = message.get("content")
        return GenerationResult(
            text="" if content is None else str(content),
            finish_reason=str(choice.get("finish_reason") or "unknown"),
            tool_trace=tuple(traces),
            usage=usage,
            response_id=str(payload["id"]) if payload.get("id") is not None else None,
        )
