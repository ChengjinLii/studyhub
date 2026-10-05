import json
from dataclasses import replace
from types import MappingProxyType

import pytest

from studyhub_agent.architectures import ReactContextArchitecture
from studyhub_agent.contracts.architecture import RunContext
from studyhub_agent.contracts.episode import Budget, Message, Termination
from studyhub_agent.contracts.prompts import COMPACTION_NOTE_PROMPT_KEY, DEFAULT_PROMPTS
from studyhub_agent.environments.replay import ReplayEnvironment
from studyhub_agent.runtime.runner import EpisodeRunner
from tests.architectures.test_hooks import SNAPSHOT, _spec
from tests.runtime.fakes import ScriptedPolicy, count_chars, final_turn, tool_turn


def _context(*, count_tokens=count_chars, budget=None, trace=None):
    return RunContext(
        spec=_spec(budget=budget or Budget()),
        turns=(),
        observations=(),
        prompts=MappingProxyType({COMPACTION_NOTE_PROMPT_KEY: DEFAULT_PROMPTS.get(COMPACTION_NOTE_PROMPT_KEY)}),
        trace={} if trace is None else trace,
        count_tokens=None if count_tokens is None else lambda messages: count_tokens(messages, (), False),
    )


def _messages():
    return (
        Message(role="system", content="系统"),
        Message(role="user", content="问题"),
        Message(
            role="tool",
            name="materials_read",
            tool_call_id="old",
            content=json.dumps(
                {"material_id": 101, "page": 1, "title": "高数提纲", "text": "极限与导数" * 500, "citation": "[101:1]"},
                ensure_ascii=False,
            ),
        ),
        Message(role="tool", name="runtime_feedback", content='{"notice":"final_turn","instruction":"最终回答"}'),
        Message(role="tool", name="materials_read", tool_call_id="recent1", content='{"text":"最近一条"}'),
        Message(role="tool", name="materials_read", tool_call_id="recent2", content='{"text":"最近两条"}'),
    )


def test_compaction_preserves_recent_tools_feedback_and_visible_identifiers() -> None:
    ctx = _context(budget=Budget(max_context_tokens=4000, max_new_tokens=100))
    messages = _messages()
    view = tuple(ReactContextArchitecture().before_step(ctx, messages))
    result = json.loads(view[2].content)
    assert result["compacted"] is True
    assert result["result"]["material_id"] == 101 and result["result"]["page"] == 1
    assert result["result"]["title"] == "高数提纲" and result["result"]["citation"] == "[101:1]"
    assert result["result"]["text"] == ("极限与导数" * 500)[:120]
    assert view[2].tool_call_id == "old" and view[2].name == "materials_read"
    assert view[3:6] == messages[3:6]
    assert messages[2].content != view[2].content
    note = json.loads(view[-1].content)
    assert note["instruction"] == DEFAULT_PROMPTS.get(COMPACTION_NOTE_PROMPT_KEY).text
    event = ctx.trace["compactions"][0]
    assert event["message_indices"] == [2] and event["messages"] == 1
    assert event["after_tokens"] < event["before_tokens"]


def test_threshold_uses_injected_tokenizer_not_character_length() -> None:
    messages = _messages()
    ctx = _context(count_tokens=lambda *_args: 10)
    assert ReactContextArchitecture().before_step(ctx, messages) == messages
    assert ctx.trace == {}


def test_at_threshold_does_not_compact() -> None:
    ctx = _context(count_tokens=lambda *_args: 8192)
    assert ReactContextArchitecture().before_step(ctx, _messages()) == _messages()


def test_missing_counter_is_not_silently_replaced_with_character_count() -> None:
    with pytest.raises(ValueError, match="token"):
        ReactContextArchitecture().before_step(_context(count_tokens=None), _messages())


def test_compaction_does_not_invent_or_expose_structured_evidence() -> None:
    from studyhub_agent.contracts.episode import Observation

    ctx = replace(
        _context(budget=Budget(max_context_tokens=4000, max_new_tokens=100)),
        observations=(
            Observation(
                call_id="old",
                name="materials_read",
                ok=True,
                payload={},
                details={"hidden_material_id": 987654, "read_pages": [[987654, 8]], "private_note": "保密字段"},
            ),
        ),
    )
    view = ReactContextArchitecture().before_step(ctx, _messages())
    encoded = json.dumps([message.model_dump() for message in view], ensure_ascii=False)
    assert "987654" not in encoded and "保密字段" not in encoded


def test_nested_search_web_memory_payloads_keep_schema_numbers_and_titles() -> None:
    payload = {
        "results": [{"material_id": 202, "title": "提纲", "price_cents": 1200, "summary": "简介" * 1000}],
        "pages": [{"url": "https://example.edu/page", "title": "网页", "text": "正文" * 1000}],
        "memory": {"learning_plan": "学习" * 1000},
        "available_keys": ["learning_plan"],
        "stored": True,
        "error": "material_locked",
        "read_first": [101],
    }
    message = Message(
        role="tool", name="web_extract", tool_call_id="c", content=json.dumps(payload, ensure_ascii=False)
    )
    architecture = ReactContextArchitecture(keep_recent_tools=0, max_text_chars=50)
    view = architecture.before_step(_context(budget=Budget(max_context_tokens=4000, max_new_tokens=100)), (message,))
    result = json.loads(view[0].content)["result"]
    assert result["results"][0]["material_id"] == 202 and result["results"][0]["price_cents"] == 1200
    assert result["pages"][0]["url"] == "https://example.edu/page" and result["pages"][0]["title"] == "网页"
    assert result["read_first"] == [101] and result["stored"] is True and result["error"] == "material_locked"
    assert result["available_keys"] == ["learning_plan"]
    assert len(result["results"][0]["summary"]) == len(result["memory"]["learning_plan"]) == 50


def test_non_json_tool_text_has_bounded_summary() -> None:
    message = Message(role="tool", name="tool", tool_call_id="c", content="原始文本" * 3000)
    view = ReactContextArchitecture(keep_recent_tools=0).before_step(_context(), (message,))
    assert json.loads(view[0].content)["result"] == message.content[:120]


@pytest.mark.parametrize("depth", [600, 2000])
def test_deep_json_does_not_crash_compaction(depth) -> None:
    content = '{"nested":' * depth + json.dumps("正文" * 10000, ensure_ascii=False) + "}" * depth
    architecture = ReactContextArchitecture(keep_recent_tools=0)
    ctx = _context(budget=Budget(max_context_tokens=1000, max_new_tokens=100))
    message = Message(role="tool", name="tool", tool_call_id="c", content=content)
    view = architecture.before_step(ctx, (message,))
    assert view and message.content == content


def test_already_compacted_large_payload_is_not_nested_again() -> None:
    content = json.dumps({"compacted": True, "result": {"title": "长标题" * 10000}}, ensure_ascii=False)
    message = Message(role="tool", name="tool", tool_call_id="c", content=content)
    ctx = _context()
    assert ReactContextArchitecture(keep_recent_tools=0).before_step(ctx, (message,)) == (message,)
    assert ctx.trace == {}


def test_compression_is_deterministic_without_recompressing_summaries() -> None:
    ctx = _context(budget=Budget(max_context_tokens=4000, max_new_tokens=100))
    architecture = ReactContextArchitecture()
    first = tuple(architecture.before_step(ctx, _messages()))
    second = tuple(architecture.before_step(ctx, _messages()))
    assert first == second
    assert architecture.before_step(ctx, first) == first
    assert sum('"notice":"context_compaction"' in message.content for message in first) == 1


def test_no_eligible_results_or_no_token_savings_keeps_full_view() -> None:
    architecture = ReactContextArchitecture()
    ctx = _context(count_tokens=lambda *_args: 100_000)
    messages = _messages()
    assert architecture.before_step(ctx, messages) == messages
    assert ctx.trace == {}
    assert architecture.before_step(ctx, messages[:2]) == messages[:2]


def test_runner_uses_compact_view_for_budget_but_records_complete_history() -> None:
    materials = tuple(
        row.model_copy(update={"preview_pages": ("预览正文" * 2000,)}) if row.material_id == 101 else row
        for row in SNAPSHOT.materials
    )
    snapshot = SNAPSHOT.model_copy(update={"materials": materials})
    turns = [
        tool_turn(("materials_search", {"query": "提纲"})),
        tool_turn(("materials_read", {"material_id": 101})),
        final_turn("[101:1]"),
    ]
    spec = _spec(budget=Budget(max_context_tokens=3000, max_new_tokens=100))
    runner = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision="test", count_tokens=count_chars)
    policy = ScriptedPolicy(list(turns))
    episode = runner.run(
        spec, ReplayEnvironment(snapshot), policy, architecture=ReactContextArchitecture(keep_recent_tools=0)
    )
    assert episode.termination is Termination.FINAL_ANSWER
    assert len(episode.observations[-1].payload["text"]) == 8000
    assert len(json.loads(episode.messages[-2].content)["text"]) == 8000
    compacted = next(message for message in policy.seen[-1] if message.tool_call_id == "t1_c0")
    assert len(json.loads(compacted.content)["result"]["text"]) == 120
    assert episode.observations[-1].details["read_pages"] == [[101, 1]]
    baseline = runner.run(spec, ReplayEnvironment(snapshot), ScriptedPolicy(list(turns)))
    assert baseline.termination is Termination.CONTEXT_BUDGET


@pytest.mark.parametrize(
    "parameters",
    [
        {"context_threshold": 0},
        {"context_threshold": 1.1},
        {"context_threshold": float("nan")},
        {"context_threshold": True},
        {"keep_recent_tools": -1},
        {"keep_recent_tools": True},
        {"max_text_chars": 0},
        {"max_text_chars": 1.5},
    ],
)
def test_invalid_compaction_parameters(parameters) -> None:
    with pytest.raises(ValueError):
        ReactContextArchitecture(**parameters)


@pytest.mark.parametrize(
    "parameters", [{"context_threshold": 0.6}, {"keep_recent_tools": 1}, {"max_text_chars": 121}]
)
def test_compaction_parameters_are_part_of_contract(parameters) -> None:
    from tests.architectures.test_hooks import RUNNER

    baseline = RUNNER.contract_for(_spec(), (), architecture=ReactContextArchitecture())
    assert RUNNER.contract_for(_spec(), (), architecture=ReactContextArchitecture(**parameters)) != baseline
