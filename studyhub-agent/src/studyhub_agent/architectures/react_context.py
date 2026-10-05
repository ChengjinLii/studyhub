import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from studyhub_agent.architectures.base import ReactArchitecture, RunContext
from studyhub_agent.contracts.episode import Message
from studyhub_agent.contracts.prompts import COMPACTION_NOTE_PROMPT_KEY

_IDENTIFIER_FIELDS = frozenset({"title", "citation", "url", "error", "key", "topic", "course", "school"})


@dataclass(frozen=True, slots=True)
class ReactContextArchitecture(ReactArchitecture):
    context_threshold: float = 0.5
    keep_recent_tools: int = 2
    max_text_chars: int = 120
    architecture_id: ClassVar[str] = "react_context"
    version: ClassVar[str] = "1.0"
    prompt_keys: ClassVar[tuple[str, ...]] = (COMPACTION_NOTE_PROMPT_KEY,)

    def __post_init__(self) -> None:
        if (
            type(self.context_threshold) not in (int, float)
            or not math.isfinite(self.context_threshold)
            or not 0 < self.context_threshold <= 1
        ):
            raise ValueError("context_threshold must be a finite number in (0, 1]")
        if type(self.keep_recent_tools) is not int or self.keep_recent_tools < 0:
            raise ValueError("keep_recent_tools must be a non-negative integer")
        if type(self.max_text_chars) is not int or self.max_text_chars < 1:
            raise ValueError("max_text_chars must be a positive integer")

    @property
    def contract_parameters(self) -> Mapping[str, Any]:
        return {
            "context_threshold": self.context_threshold,
            "keep_recent_tools": self.keep_recent_tools,
            "max_text_chars": self.max_text_chars,
        }

    def before_step(self, ctx: RunContext, messages: Sequence[Message]) -> Sequence[Message]:
        if ctx.count_tokens is None:
            raise ValueError("react_context requires an exact token counter from the runner")
        before_tokens = ctx.count_tokens(messages)
        if before_tokens <= ctx.spec.budget.max_context_tokens * self.context_threshold:
            return messages
        eligible = [
            index
            for index, message in enumerate(messages)
            if message.role == "tool" and message.tool_call_id is not None and message.name != "runtime_feedback"
        ]
        older = eligible[: -self.keep_recent_tools] if self.keep_recent_tools else eligible
        view = list(messages)
        changed = []
        for index in older:
            summary = self._summary(messages[index].content)
            if len(summary) < len(messages[index].content):
                view[index] = messages[index].model_copy(update={"content": summary})
                changed.append(index)
        if not changed:
            return messages
        view.append(
            Message(
                role="tool",
                name="runtime_feedback",
                content=json.dumps(
                    {"notice": "context_compaction", "instruction": ctx.prompts[COMPACTION_NOTE_PROMPT_KEY].text},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        after_tokens = ctx.count_tokens(view)
        if after_tokens >= before_tokens:
            return messages
        ctx.trace.setdefault("compactions", []).append(
            {
                "turn": len(ctx.turns),
                "messages": len(changed),
                "message_indices": changed,
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
            }
        )
        return tuple(view)

    def _summary(self, content: str) -> str:
        try:
            payload = json.loads(content)
        except (ValueError, RecursionError):
            payload = content
        if isinstance(payload, dict) and payload.get("compacted") is True and "result" in payload:
            return content
        # Only model-visible content is summarized; structured evidence must not enter the prompt.
        try:
            return json.dumps(
                {"compacted": True, "result": self._compact(payload)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except RecursionError:
            return content

    def _compact(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {field: self._compact(item, field) for field, item in value.items()}
        if isinstance(value, list):
            return [self._compact(item, key) for item in value]
        if isinstance(value, str) and key not in _IDENTIFIER_FIELDS:
            return value[: self.max_text_chars]
        return value
