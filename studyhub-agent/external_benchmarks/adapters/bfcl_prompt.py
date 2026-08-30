"""Prompt-boundary helpers for the StudyHub BFCL model adapter."""

from __future__ import annotations


def disable_thinking_generation_prefix(prompt: str) -> str:
    suffix = "<|im_start|>assistant\n"
    if not prompt.endswith(suffix):
        raise RuntimeError("BFCL Qwen FC prompt has an unexpected generation suffix")
    return prompt + "<think>\n\n</think>\n\n"
