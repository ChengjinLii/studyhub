from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from ai_platform.observability.usage_tracker import JsonlUsageTracker, UsageEvent, get_env_usage_tracker


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatCompletionRequest:
    messages: list[ChatMessage]
    temperature: float = 0.1
    max_tokens: int = 1200
    response_format: dict[str, str] | None = None


@dataclass(frozen=True)
class ChatCompletionResponse:
    provider: str
    model: str
    content: str
    usage: dict[str, int]


class ChatProvider(Protocol):
    name: str
    model: str

    def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        ...


class OpenAICompatibleChatProvider:
    """Minimal OpenAI-compatible chat provider for isolated API smoke tests.

    API keys are read from environment variables only. This provider is not used
    by default tests and never logs prompt payloads or credentials.
    """

    name = "openai-compatible-chat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        usage_tracker: JsonlUsageTracker | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.usage_tracker = usage_tracker

    def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [message.to_dict() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format:
            payload["response_format"] = request.response_format
        body = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            self._record_usage(status="error", operation="chat.completions", error_type=exc.__class__.__name__)
            raise RuntimeError("chat provider request failed") from exc
        data = json.loads(raw)
        content = str(data["choices"][0]["message"]["content"])
        usage = data.get("usage") or {}
        normalized_usage = {
            "promptTokens": int(usage.get("prompt_tokens") or 0),
            "completionTokens": int(usage.get("completion_tokens") or 0),
            "totalTokens": int(usage.get("total_tokens") or 0),
        }
        self._record_usage(status="success", operation="chat.completions", **normalized_usage)
        return ChatCompletionResponse(
            provider=self.name,
            model=self.model,
            content=content,
            usage=normalized_usage,
        )

    def _record_usage(
        self,
        *,
        status: str,
        operation: str,
        promptTokens: int = 0,
        completionTokens: int = 0,
        totalTokens: int = 0,
        error_type: str | None = None,
    ) -> None:
        if not self.usage_tracker:
            return
        self.usage_tracker.record(
            UsageEvent(
                provider=self.name,
                model=self.model,
                operation=operation,
                status=status,
                prompt_tokens=promptTokens,
                completion_tokens=completionTokens,
                total_tokens=totalTokens,
                error_type=error_type,
            )
        )


def get_env_chat_provider(prefix: str = "STUDYHUB_LLM") -> OpenAICompatibleChatProvider | None:
    base_url = os.getenv(f"{prefix}_BASE_URL")
    api_key = os.getenv(f"{prefix}_API_KEY")
    model = os.getenv(f"{prefix}_MODEL")
    if not base_url or not api_key or not model:
        return None
    return OpenAICompatibleChatProvider(base_url=base_url, api_key=api_key, model=model, usage_tracker=get_env_usage_tracker())
