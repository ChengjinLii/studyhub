from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import httpx

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling, ToolCall, TurnKind
from studyhub_agent.contracts.render import RenderError, canonical_completion_text, parse_completion
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.tokenizer import Tokenizer


def _wire_message(message: Message) -> dict[str, Any]:
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                }
                for call in message.tool_calls
            ],
        }
    if message.role == "tool":
        if message.tool_call_id:
            return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id}
        # No real tool_call_id to bind to (e.g. runtime feedback: parse-error notices, the finalize
        # prompt). A fake id would match no assistant tool call and strict servers reject that, so
        # send the same text the Qwen template itself produces for a standalone tool turn.
        return {"role": "user", "content": f"<tool_response>\n{message.content}\n</tool_response>"}
    return {"role": message.role, "content": message.content}


def _raw_completion_text(content: str, tool_calls: Any) -> str:
    """The assistant content plus, if present, the raw tool_calls JSON on a new line.

    Used for both AssistantTurn.raw_text and PARSE_ERROR feedback: the runner feeds raw_text back
    into history on a parse error, so it must never be the whole response envelope.
    """
    if tool_calls:
        return f"{content}\n{json.dumps(tool_calls, ensure_ascii=False)}"
    return content


class OpenAICompatPolicyClient:
    """Teacher/baseline client. Its turns are re-rendered through the single renderer before any use as data."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        tokenizer: Tokenizer | None = None,
        timeout_s: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/v1/chat/completions"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._tokenizer = tokenizer
        self._client = client or httpx.Client(timeout=timeout_s)

    def step(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        thinking: bool,
        sampling: Sampling,
        max_new_tokens: int,
    ) -> AssistantTurn:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [_wire_message(message) for message in messages],
            "tools": [tool.to_openai() for tool in tools],
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_tokens": max_new_tokens,
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
        if sampling.seed is not None:
            body["seed"] = sampling.seed
        started = time.perf_counter()
        try:
            response = self._client.post(self._url, json=body, headers=self._headers)
            response.raise_for_status()
            choice = response.json()["choices"][0]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise PolicyInfraError(f"chat completion failed: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        return self._to_turn(messages, tools, choice, thinking=thinking, latency_ms=latency_ms)

    def _to_turn(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        choice: dict[str, Any],
        *,
        thinking: bool,
        latency_ms: float,
    ) -> AssistantTurn:
        message = choice.get("message") or {}
        content = (message.get("content") or "").strip()
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        raw_text = _raw_completion_text(content, message.get("tool_calls"))
        calls: list[ToolCall] = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                return self._error(raw_text, f"invalid_arguments_json: {function.get('name')}", choice, latency_ms)
            if not isinstance(arguments, dict):
                return self._error(raw_text, f"invalid_arguments_json: {function.get('name')}", choice, latency_ms)
            calls.append(ToolCall(call_id=f"call_{index}", name=str(function.get("name")), arguments=arguments))
        if not calls and not content:
            return self._error(raw_text, "empty_response", choice, latency_ms)
        assistant = Message(role="assistant", content=content, tool_calls=tuple(calls), reasoning=reasoning)
        try:
            canonical = canonical_completion_text(messages, assistant, tools, thinking=thinking)
        except RenderError as exc:
            return self._error(raw_text, f"unrenderable: {exc}", choice, latency_ms)
        reparsed = parse_completion(canonical, tools, thinking=thinking)
        if reparsed.kind is TurnKind.PARSE_ERROR:
            return self._error(raw_text, reparsed.error or "parse_error", choice, latency_ms)
        return AssistantTurn(
            kind=reparsed.kind,
            content=reparsed.content,
            reasoning=reparsed.reasoning,
            tool_calls=reparsed.tool_calls,
            raw_text=raw_text,
            canonical_text=canonical,
            completion_token_ids=tuple(self._tokenizer.encode(canonical)) if self._tokenizer else (),
            server_parse_mismatch=reparsed.tool_calls != tuple(calls),
            finish_reason=choice.get("finish_reason"),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _error(raw_text: str, error: str, choice: dict[str, Any], latency_ms: float) -> AssistantTurn:
        return AssistantTurn(
            kind=TurnKind.PARSE_ERROR,
            raw_text=raw_text,
            canonical_text=raw_text,
            parse_error=error,
            finish_reason=choice.get("finish_reason"),
            latency_ms=latency_ms,
        )
