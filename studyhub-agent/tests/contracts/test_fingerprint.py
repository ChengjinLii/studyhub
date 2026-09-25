import dataclasses

import pytest

from studyhub_agent.contracts.fingerprint import ContractInputs, contract_hash
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS, FINALIZE_PROMPT_KEY, SYSTEM_PROMPT_KEY, PromptTemplate
from studyhub_agent.contracts.tools import ToolSpec


def _tool(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1.0",
        description="d",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    )


BASE = ContractInputs(
    system_prompt=DEFAULT_PROMPTS.get(SYSTEM_PROMPT_KEY),
    finalize_prompt=DEFAULT_PROMPTS.get(FINALIZE_PROMPT_KEY),
    tools=(_tool("a"), _tool("b")),
    thinking=False,
    tokenizer_revision="qwen3.5-4b@rev1",
    max_context_tokens=16384,
    max_new_tokens=2048,
)


def test_hash_format_and_determinism() -> None:
    value = contract_hash(BASE)
    assert value.startswith("sha256:") and len(value) == len("sha256:") + 64
    assert contract_hash(BASE) == value


def test_tool_order_now_changes_the_hash() -> None:
    # select_tools() (contracts.tools/tools.specs) always hands the runner canonical order, so in
    # practice tool order never varies for a given episode spec. But contract_hash must not paper
    # over an order difference if one ever reaches it: render_text puts tools into the prompt in
    # list order, so a hash that ignored order could give two different prompts the same hash.
    assert contract_hash(dataclasses.replace(BASE, tools=(_tool("b"), _tool("a")))) != contract_hash(BASE)


def test_tool_parameter_order_changes_the_hash() -> None:
    def _tool_with_props(order: list[str]) -> ToolSpec:
        return ToolSpec(
            name="t",
            version="1.0",
            description="d",
            parameters={
                "type": "object",
                "properties": {key: {"type": "string", "description": "d"} for key in order},
                "required": [],
                "additionalProperties": False,
            },
        )

    xy = dataclasses.replace(BASE, tools=(_tool_with_props(["x", "y"]),))
    yx = dataclasses.replace(BASE, tools=(_tool_with_props(["y", "x"]),))
    assert contract_hash(xy) != contract_hash(yx)


@pytest.mark.parametrize(
    "change",
    [
        {"thinking": True},
        {"tokenizer_revision": "qwen3.5-4b@rev2"},
        {"max_context_tokens": 8192},
        {"max_new_tokens": 1024},
        {"template_sha256": "0" * 64},
        {"turn_rule_version": "turn-rule@2"},
        {"tools": (_tool("a"),)},
        {"system_prompt": PromptTemplate("studyhub.agent.system", "1.1", "新提示")},
        {"finalize_prompt": PromptTemplate("studyhub.agent.finalize", "1.1", "新收尾")},
    ],
)
def test_every_component_changes_the_hash(change) -> None:
    assert contract_hash(dataclasses.replace(BASE, **change)) != contract_hash(BASE)
