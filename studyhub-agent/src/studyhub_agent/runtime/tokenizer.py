from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from studyhub_agent.contracts.episode import Message
from studyhub_agent.contracts.render import render_text
from studyhub_agent.contracts.tools import ToolSpec


class Tokenizer(Protocol):
    stop_token_ids: tuple[int, ...]

    def encode(self, text: str) -> list[int]: ...

    def decode(self, ids: Sequence[int]) -> str: ...


class HFTokenizer:
    """Thin wrapper over the model's tokenizer.json (no transformers dependency)."""

    def __init__(self, backend, stop_token_ids: tuple[int, ...]) -> None:
        self._backend = backend
        self.stop_token_ids = stop_token_ids

    @classmethod
    def from_model_dir(cls, path: Path) -> HFTokenizer:
        from tokenizers import Tokenizer as RawTokenizer

        backend = RawTokenizer.from_file(str(path / "tokenizer.json"))
        stops = tuple(
            token_id
            for token_id in (backend.token_to_id("<|im_end|>"), backend.token_to_id("<|endoftext|>"))
            if token_id is not None
        )
        return cls(backend, stops)

    def encode(self, text: str) -> list[int]:
        return self._backend.encode(text, add_special_tokens=False).ids

    def decode(self, ids: Sequence[int]) -> str:
        return self._backend.decode(list(ids), skip_special_tokens=False)


def token_counter(tokenizer: Tokenizer):
    def count(messages: Sequence[Message], tools: Sequence[ToolSpec], thinking: bool) -> int:
        return len(tokenizer.encode(render_text(messages, tools, thinking=thinking, add_generation_prompt=True)))

    return count
