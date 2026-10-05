from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from studyhub_agent.contracts.episode import Message
from studyhub_agent.contracts.prompts import PromptTemplate
from studyhub_agent.contracts.render import TEMPLATE_SHA256, render_text
from studyhub_agent.contracts.tools import ToolSpec

TURN_RULE_VERSION = "turn-rule@1"


@dataclass(frozen=True, slots=True)
class ContractInputs:
    system_prompt: PromptTemplate
    finalize_prompt: PromptTemplate
    tools: tuple[ToolSpec, ...]
    thinking: bool
    tokenizer_revision: str
    max_context_tokens: int
    max_new_tokens: int
    template_sha256: str = TEMPLATE_SHA256
    turn_rule_version: str = TURN_RULE_VERSION
    architecture: str = "react@1.0"
    architecture_prompts: tuple[PromptTemplate, ...] = ()
    architecture_parameters: dict[str, Any] = field(default_factory=dict)
    models: tuple[tuple[str, str, str], ...] = ()
    max_turns: int = 12
    max_tool_calls: int = 16
    max_parse_errors: int = 2


def contract_hash(inputs: ContractInputs) -> str:
    # The "tools" field below sorts by name, which makes it blind to tool *order* and (since
    # canonical() now preserves schema key order) to the fact that json.dumps recursion would
    # otherwise ignore it anyway. render_text renders tools and messages in list order, so a hash
    # that only looked at the sorted canonical form could give two different prompts (different
    # tool order, or -- pre-I2 -- different schema key order) the same hash. Guard against any such
    # drift directly: hash the actual rendered system+tools prefix the model would see.
    # The chat template unconditionally requires a real (non-tool-response) user turn anywhere in
    # the message list, even when only checking the system+tools preamble, so a bare [system]
    # sequence raises RenderError("No user query found in messages."). An empty placeholder user
    # message satisfies that check without adding any real content to what we're hashing.
    rendered_prefix = render_text(
        (Message(role="system", content=inputs.system_prompt.text), Message(role="user", content="")),
        inputs.tools,
        thinking=inputs.thinking,
        add_generation_prompt=False,
    )
    document = {
        "system_prompt": {"key": inputs.system_prompt.key, "text": inputs.system_prompt.text},
        "finalize_prompt": {"key": inputs.finalize_prompt.key, "text": inputs.finalize_prompt.text},
        "tools": sorted((tool.canonical() for tool in inputs.tools), key=lambda item: item["name"]),
        "thinking": inputs.thinking,
        "tokenizer_revision": inputs.tokenizer_revision,
        "max_context_tokens": inputs.max_context_tokens,
        "max_new_tokens": inputs.max_new_tokens,
        "template_sha256": inputs.template_sha256,
        "turn_rule_version": inputs.turn_rule_version,
        "rendered_prefix_sha256": hashlib.sha256(rendered_prefix.encode("utf-8")).hexdigest(),
        "architecture": inputs.architecture,
        "architecture_prompts": [{"key": prompt.key, "text": prompt.text} for prompt in inputs.architecture_prompts],
        "architecture_parameters": json.loads(
            json.dumps(inputs.architecture_parameters, sort_keys=True, allow_nan=False)
        ),
        "models": sorted(inputs.models),
        "max_turns": inputs.max_turns,
        "max_tool_calls": inputs.max_tool_calls,
        "max_parse_errors": inputs.max_parse_errors,
    }
    # No sort_keys: `document`'s key order is fixed by this literal, and sort_keys=True would
    # recursively re-sort every nested dict (including each tool's `parameters`/`properties`),
    # silently undoing canonical()'s order-preserving fix above.
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
