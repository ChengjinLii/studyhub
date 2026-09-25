from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling, TurnKind
from studyhub_agent.contracts.render import (
    END_OF_TURN,
    RenderError,
    canonical_completion_text,
    parse_completion,
    render_text,
)
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.tokenizer import Tokenizer


@dataclass(frozen=True, slots=True)
class Generation:
    output_ids: tuple[int, ...]
    logprobs: tuple[float, ...]
    finish_reason: str | None


class GenerateBackend(Protocol):
    def generate(
        self, input_ids: Sequence[int], *, sampling: Sampling, max_new_tokens: int, stop_token_ids: Sequence[int]
    ) -> Generation: ...


class SGLangGenerateBackend:
    def __init__(self, base_url: str, *, timeout_s: float = 120.0, client: httpx.Client | None = None) -> None:
        self._url = base_url.rstrip("/") + "/generate"
        self._client = client or httpx.Client(timeout=timeout_s)

    def generate(
        self, input_ids: Sequence[int], *, sampling: Sampling, max_new_tokens: int, stop_token_ids: Sequence[int]
    ) -> Generation:
        params = {
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_new_tokens": max_new_tokens,
            "stop_token_ids": list(stop_token_ids),
            "skip_special_tokens": False,
        }
        if sampling.seed is not None:
            params["sampling_seed"] = sampling.seed
        try:
            response = self._client.post(
                self._url,
                json={"input_ids": list(input_ids), "sampling_params": params, "return_logprob": True},
            )
            response.raise_for_status()
            meta = response.json()["meta_info"]
            pairs = meta.get("output_token_logprobs")
            if pairs is None:
                raise PolicyInfraError("sglang response is missing output_token_logprobs")
            finish = meta.get("finish_reason")
            finish_reason = finish.get("type") if isinstance(finish, dict) else finish
            if finish_reason == "abort":
                # The request was cancelled/aborted at the infra level (e.g. server shutdown); this
                # is not a model output, so it must never reach the parser as a real completion.
                raise PolicyInfraError("sglang generate aborted")
            return Generation(
                output_ids=tuple(int(item[1]) for item in pairs),
                logprobs=tuple(float(item[0]) for item in pairs),
                finish_reason=finish_reason,
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as exc:
            raise PolicyInfraError(f"sglang generate failed: {exc}") from exc


class TokenPolicyClient:
    def __init__(self, tokenizer: Tokenizer, backend: GenerateBackend) -> None:
        self._tokenizer = tokenizer
        self._backend = backend

    def step(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        thinking: bool,
        sampling: Sampling,
        max_new_tokens: int,
    ) -> AssistantTurn:
        prompt_ids = self._tokenizer.encode(render_text(messages, tools, thinking=thinking, add_generation_prompt=True))
        started = time.perf_counter()
        generation = self._backend.generate(
            prompt_ids, sampling=sampling, max_new_tokens=max_new_tokens, stop_token_ids=self._tokenizer.stop_token_ids
        )
        latency_ms = (time.perf_counter() - started) * 1000
        raw_text = self._tokenizer.decode(generation.output_ids).split(END_OF_TURN, 1)[0]
        if generation.finish_reason == "length":
            # The completion was cut off by max_new_tokens; it must never be treated as a valid
            # FINAL/TOOL_CALLS turn (that would silently produce truncated SFT data).
            return self._parse_error_turn(raw_text, "truncated", prompt_ids, generation, latency_ms)
        parsed = parse_completion(raw_text, tools, thinking=thinking)
        canonical = raw_text
        if parsed.kind is not TurnKind.PARSE_ERROR:
            assistant = Message(
                role="assistant", content=parsed.content, tool_calls=parsed.tool_calls, reasoning=parsed.reasoning
            )
            try:
                canonical = canonical_completion_text(messages, assistant, tools, thinking=thinking)
            except RenderError as exc:
                return self._parse_error_turn(raw_text, f"unrenderable: {exc}", prompt_ids, generation, latency_ms)
        stripped_canonical = canonical.removesuffix(END_OF_TURN + "\n")
        non_canonical = parsed.kind is not TurnKind.PARSE_ERROR and stripped_canonical != raw_text
        return AssistantTurn(
            kind=parsed.kind,
            content=parsed.content,
            reasoning=parsed.reasoning,
            tool_calls=parsed.tool_calls,
            raw_text=raw_text,
            canonical_text=canonical,
            parse_error=parsed.error,
            prompt_token_ids=tuple(prompt_ids),
            sampled_token_ids=generation.output_ids,
            canonical_token_ids=tuple(self._tokenizer.encode(canonical)),
            completion_logprobs=generation.logprobs,
            non_canonical=non_canonical,
            finish_reason=generation.finish_reason,
            latency_ms=latency_ms,
        )

    def _parse_error_turn(
        self, raw_text: str, error: str, prompt_ids: Sequence[int], generation: Generation, latency_ms: float
    ) -> AssistantTurn:
        return AssistantTurn(
            kind=TurnKind.PARSE_ERROR,
            raw_text=raw_text,
            canonical_text=raw_text,
            parse_error=error,
            prompt_token_ids=tuple(prompt_ids),
            sampled_token_ids=generation.output_ids,
            canonical_token_ids=tuple(self._tokenizer.encode(raw_text)),
            completion_logprobs=generation.logprobs,
            finish_reason=generation.finish_reason,
            latency_ms=latency_ms,
        )
