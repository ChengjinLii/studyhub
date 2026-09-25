from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from studyhub_agent.contracts.prompts import PromptTemplate
from studyhub_agent.contracts.render import TEMPLATE_SHA256
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


def contract_hash(inputs: ContractInputs) -> str:
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
    }
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
