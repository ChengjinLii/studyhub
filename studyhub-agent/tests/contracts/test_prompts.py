import pytest

from studyhub_agent.contracts.prompts import (
    DEFAULT_PROMPTS,
    FINALIZE_PROMPT_KEY,
    SYSTEM_PROMPT_KEY,
    PromptRegistry,
    PromptTemplate,
)


def test_default_registry_has_system_and_finalize_prompts() -> None:
    assert DEFAULT_PROMPTS.get(SYSTEM_PROMPT_KEY).text.strip()
    assert DEFAULT_PROMPTS.get(FINALIZE_PROMPT_KEY).text.strip()


def test_duplicate_keys_are_rejected() -> None:
    prompt = PromptTemplate("p", "1.0", "text")
    with pytest.raises(ValueError, match="duplicate"):
        PromptRegistry([prompt, prompt])


def test_unknown_key_raises_with_known_keys_listed() -> None:
    with pytest.raises(KeyError, match="studyhub.agent.system@1.0"):
        DEFAULT_PROMPTS.get("missing@9.9")


def test_with_prompt_returns_new_registry_without_mutating() -> None:
    extended = DEFAULT_PROMPTS.with_prompt(PromptTemplate("extra", "1.0", "hi"))
    assert "extra@1.0" in extended.keys()
    assert "extra@1.0" not in DEFAULT_PROMPTS.keys()


def test_prompt_version_must_be_numeric() -> None:
    with pytest.raises(ValueError, match="version"):
        PromptTemplate("p", "latest", "text")
