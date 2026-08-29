from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import yaml

from scripts.data.build_open_rl_tasks import parse_toolace_trajectory
from training.rl.config import (
    AGENT_ENGINE_MAX_TOKENS,
    AGENT_MAX_TURNS,
    CONTEXT_FINALIZATION_RATIO,
    CONTEXT_SAFETY_MARGIN_TOKENS,
    StudyHubAgentGRPOConfig,
)
from training.rl.frozen_environment import SEARCH_SNIPPET_CHARS, FrozenTaskEnvironment
from training.rl.hermes_workflow import (
    CONTEXT_FINALIZATION_GUIDANCE,
    SYSTEM_PROMPT,
    ContextBudgetController,
    StudyHubHermesWorkflow,
    _enable_training_tool_guardrails,
    _install_training_system_prompt,
    _training_runtime_metadata,
)
from training.rl.reward_v2 import evaluate_reward_v2


def test_hermes_loader_disables_optional_relay_for_frozen_rollouts(
    monkeypatch, tmp_path
) -> None:
    checkout = tmp_path / "hermes"
    checkout.mkdir()
    hosts = {}
    relay_runtime = ModuleType("agent.relay_runtime")
    relay_runtime.current_profile_key = lambda: "test-profile"
    relay_runtime.HOST_REGISTRY = SimpleNamespace(
        _lock=threading.RLock(),
        _hosts=hosts,
    )
    relay_runtime.NoopRelayRuntime = lambda **kwargs: kwargs
    agent_package = ModuleType("agent")
    agent_package.relay_runtime = relay_runtime
    run_agent = ModuleType("run_agent")
    run_agent.AIAgent = object
    registry = object()
    tools_package = ModuleType("tools")
    tool_search = ModuleType("tools.tool_search")

    class ToolSearchConfig:
        @classmethod
        def from_raw(cls, raw):
            return SimpleNamespace(enabled=raw["enabled"])

    tool_search.ToolSearchConfig = ToolSearchConfig
    tool_search.load_config = lambda: SimpleNamespace(enabled="on")
    tools_package.tool_search = tool_search
    tools_registry = ModuleType("tools.registry")
    tools_registry.registry = registry
    monkeypatch.setitem(sys.modules, "agent", agent_package)
    monkeypatch.setitem(sys.modules, "agent.relay_runtime", relay_runtime)
    monkeypatch.setitem(sys.modules, "run_agent", run_agent)
    monkeypatch.setitem(sys.modules, "tools", tools_package)
    monkeypatch.setitem(sys.modules, "tools.tool_search", tool_search)
    monkeypatch.setitem(sys.modules, "tools.registry", tools_registry)
    workflow = object.__new__(StudyHubHermesWorkflow)
    workflow.hermes_checkout = checkout

    loaded_agent, loaded_registry = workflow._load_hermes()

    assert loaded_agent is object
    assert loaded_registry is registry
    assert hosts["test-profile"]["reason"] == "disabled for StudyHub frozen RL rollout"
    assert tool_search.load_config().enabled == "off"


def test_grpo_config_limits_sglang_to_one_lora_slot() -> None:
    config = StudyHubAgentGRPOConfig()

    assert config.sglang.max_loaded_loras == 1
    assert config.sglang.max_loras_per_batch == 1


def test_grpo_config_uses_non_jit_sampling_backend() -> None:
    config = StudyHubAgentGRPOConfig()

    assert config.sglang.sampling_backend == "pytorch"


def test_grpo_config_caps_exported_interactions_at_microbatch_capacity() -> None:
    config = StudyHubAgentGRPOConfig()

    assert config.rollout.agent.engine_max_tokens == AGENT_ENGINE_MAX_TOKENS
    assert AGENT_ENGINE_MAX_TOKENS == 4096
    assert config.max_turns == AGENT_MAX_TURNS == 6
    assert config.rollout.agent.chat_template_type == "hf"
    assert config.rollout.agent.export_style == "individual"
    assert config.context_finalization_ratio == CONTEXT_FINALIZATION_RATIO == 0.80
    assert config.context_safety_margin_tokens == CONTEXT_SAFETY_MARGIN_TOKENS == 768


def test_eval_launcher_enforces_deterministic_non_updating_protocol() -> None:
    project_root = Path(__file__).parents[3]
    launcher = (project_root / "scripts/train/run_controlled_grpo.sh").read_text()

    for contract in (
        "actor.optimizer.lr=0.0",
        "rollout.deterministic_sampling=true",
        "rollout.max_head_offpolicyness=0",
        "sglang.enable_deterministic_inference=true",
        "open_agent_rl_dev_eval32_v2",
        "--require-unchanged-lora",
    ):
        assert contract in launcher


def test_training_prompt_keeps_only_studyhub_constraints() -> None:
    agent = SimpleNamespace(
        _build_system_prompt=lambda _message=None: "Hermes interactive prompt",
        _cached_system_prompt="cached",
        _cached_system_prompt_static="cached-static",
        ephemeral_system_prompt=SYSTEM_PROMPT,
    )

    _install_training_system_prompt(agent)

    assert agent._build_system_prompt() == SYSTEM_PROMPT
    assert agent._build_system_prompt("extra constraint") == (
        f"{SYSTEM_PROMPT}\n\nextra constraint"
    )
    assert agent._cached_system_prompt is None
    assert agent._cached_system_prompt_static is None
    assert agent.ephemeral_system_prompt is None


def test_grpo_zeros_outcome_reward_for_truncated_no_eos_generations() -> None:
    project_root = Path(__file__).parents[3]
    config = yaml.safe_load(
        (project_root / "configs/train/open-grpo-qwen35-4b.yaml").read_text()
    )

    assert config["actor"]["mask_no_eos_with_zero"] is True


def test_training_rollouts_enable_hermes_hard_stop_guardrails(monkeypatch) -> None:
    guardrails = ModuleType("agent.tool_guardrails")

    class ToolCallGuardrailConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ToolCallGuardrailController:
        def __init__(self, config):
            self.config = config

    guardrails.ToolCallGuardrailConfig = ToolCallGuardrailConfig
    guardrails.ToolCallGuardrailController = ToolCallGuardrailController
    agent_package = ModuleType("agent")
    agent_package.__path__ = []
    monkeypatch.setitem(sys.modules, "agent", agent_package)
    monkeypatch.setitem(sys.modules, "agent.tool_guardrails", guardrails)
    agent = SimpleNamespace(_tool_guardrail_halt_decision="stale")

    _enable_training_tool_guardrails(agent, ["knowledge_search", "knowledge_read"])

    config = agent._tool_guardrails.config
    assert config.hard_stop_enabled is True
    assert config.exact_failure_block_after == 3
    assert config.same_tool_failure_halt_after == 5
    assert config.no_progress_block_after == 3
    assert config.idempotent_tools == frozenset(
        {"knowledge_search", "knowledge_read"}
    )
    assert config.mutating_tools == frozenset()
    assert agent._tool_guardrail_halt_decision is None


def test_training_runtime_metadata_records_guardrail_and_token_usage() -> None:
    decision = SimpleNamespace(to_metadata=lambda: {"code": "loop_halt"})
    agent = SimpleNamespace(
        _tool_guardrail_halt_decision=decision,
        _api_call_count=4,
        session_input_tokens=100,
        session_output_tokens=20,
        session_prompt_tokens=90,
        session_completion_tokens=10,
        session_total_tokens=120,
        context_compressor=SimpleNamespace(last_prompt_tokens=88),
    )

    assert _training_runtime_metadata(agent) == {
        "guardrail_halt": {"code": "loop_halt"},
        "api_calls": 4,
        "input_tokens": 100,
        "output_tokens": 20,
        "prompt_tokens": 90,
        "completion_tokens": 10,
        "total_tokens": 120,
        "last_prompt_tokens": 88,
        "context_budget": None,
    }


def test_context_budget_guard_forces_a_final_turn_before_engine_limit(monkeypatch) -> None:
    def fake_count(_tokenizer, kwargs):
        message_chars = sum(len(str(row.get("content", ""))) for row in kwargs["messages"])
        return message_chars + (1000 if kwargs.get("tools") else 0)

    monkeypatch.setattr("training.rl.hermes_workflow._request_token_count", fake_count)
    tools = [{"type": "function", "function": {"name": "knowledge_read"}}]
    agent = SimpleNamespace(
        tools=tools,
        max_iterations=6,
        _handle_max_iterations=lambda _messages, _count: "upstream-summary",
    )

    def original(messages, tools_for_api=None):
        selected = tools if tools_for_api is None else tools_for_api
        return {"messages": messages, "tools": selected, "max_tokens": 1536}

    agent._build_api_kwargs = original
    runtime_errors = []
    controller = ContextBudgetController(
        tokenizer=object(),
        engine_max_tokens=4096,
        finalization_ratio=0.80,
        safety_margin_tokens=256,
        runtime_error_callback=runtime_errors.append,
    )
    controller.install(agent)
    messages = [
        {"role": "system", "content": "s" * 300},
        {"role": "user", "content": "u" * 300},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "e" * 1800, "tool_call_id": "1"},
    ]

    kwargs = agent._build_api_kwargs(messages)

    assert "tools" not in kwargs
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert kwargs["metadata"]["studyhub_chat_template"] == "disable_thinking_v1"
    assert CONTEXT_FINALIZATION_GUIDANCE in kwargs["messages"][-1]["content"]
    assert kwargs["max_tokens"] <= 4096 - fake_count(None, kwargs)
    assert kwargs["max_tokens"] <= 256
    assert controller.telemetry.forced_final_count == 1
    assert controller.telemetry.forced_final_reasons == ["context_threshold"]
    assert controller.telemetry.finalization_thinking_disabled is True
    assert controller.telemetry.final_completion_cap_tokens == kwargs["max_tokens"]
    assert controller.telemetry.max_sent_prompt_tokens < 4096
    assert runtime_errors == []


def test_context_budget_guard_compacts_large_tool_observations(monkeypatch) -> None:
    def fake_count(_tokenizer, kwargs):
        return sum(len(str(row.get("content", ""))) for row in kwargs["messages"])

    monkeypatch.setattr("training.rl.hermes_workflow._request_token_count", fake_count)
    agent = SimpleNamespace(
        tools=[],
        max_iterations=6,
        _handle_max_iterations=lambda _messages, _count: "upstream-summary",
    )
    agent._build_api_kwargs = lambda messages, tools_for_api=None: {
        "messages": messages,
        "tools": tools_for_api or [],
        "max_tokens": 1536,
    }
    runtime_errors = []
    controller = ContextBudgetController(
        tokenizer=object(),
        engine_max_tokens=4096,
        finalization_ratio=0.80,
        safety_margin_tokens=256,
        runtime_error_callback=runtime_errors.append,
    )
    controller.install(agent)
    messages = [
        {"role": "system", "content": "s" * 600},
        {"role": "user", "content": "u" * 600},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {
            "role": "tool",
            "content": json.dumps({"source_id": "src-abc", "text": "e" * 4000}),
            "tool_call_id": "1",
        },
    ]

    kwargs = agent._build_api_kwargs(messages)

    assert fake_count(None, kwargs) <= 4096 - 256
    assert controller.telemetry.compacted_tool_messages == 1
    assert controller.telemetry.dropped_tool_exchanges == 0
    assert runtime_errors == []


def test_context_budget_counter_failure_stops_without_provider_retry(monkeypatch) -> None:
    monkeypatch.setattr(
        "training.rl.hermes_workflow._request_token_count",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad template")),
    )
    agent = SimpleNamespace(
        tools=[],
        max_iterations=6,
        _handle_max_iterations=lambda _messages, _count: "upstream-summary",
    )
    agent._build_api_kwargs = lambda messages, tools_for_api=None: {
        "messages": messages,
        "max_tokens": 128,
    }
    runtime_errors = []
    controller = ContextBudgetController(
        tokenizer=object(),
        engine_max_tokens=4096,
        finalization_ratio=0.80,
        safety_margin_tokens=256,
        runtime_error_callback=runtime_errors.append,
    )
    controller.install(agent)

    try:
        agent._build_api_kwargs([{"role": "user", "content": "hello"}])
    except ValueError as error:
        assert str(error) == "bad template"
    else:
        raise AssertionError("context tokenization failure must fail closed")

    assert agent.max_iterations == 0
    assert runtime_errors == ["context_budget_counter_failed"]


def test_context_budget_uses_last_model_turn_for_final_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        "training.rl.hermes_workflow._request_token_count",
        lambda _tokenizer, kwargs: sum(
            len(str(row.get("content", ""))) for row in kwargs["messages"]
        ),
    )
    tools = [{"type": "function", "function": {"name": "knowledge_search"}}]
    agent = SimpleNamespace(
        tools=tools,
        max_iterations=6,
        iteration_budget=SimpleNamespace(remaining=0),
        _handle_max_iterations=lambda _messages, _count: "provider-summary",
    )
    agent._build_api_kwargs = lambda messages, tools_for_api=None: {
        "messages": messages,
        "tools": tools if tools_for_api is None else tools_for_api,
        "max_tokens": 1536,
    }
    runtime_errors = []
    controller = ContextBudgetController(
        tokenizer=object(),
        engine_max_tokens=4096,
        finalization_ratio=0.80,
        safety_margin_tokens=256,
        runtime_error_callback=runtime_errors.append,
    )
    controller.install(agent)

    kwargs = agent._build_api_kwargs([{"role": "user", "content": "short task"}])

    assert "tools" not in kwargs
    assert controller.telemetry.forced_final_reasons == ["model_turn_budget"]
    assert CONTEXT_FINALIZATION_GUIDANCE in kwargs["messages"][-1]["content"]
    assert runtime_errors == []

    # Hermes' separate max-iteration summary path bypasses normal request
    # building upstream. Controlled training must fail closed instead.
    assert agent._handle_max_iterations([], 6) == ""
    assert runtime_errors == ["context_budget_finalization_failed"]


def test_context_budget_requires_the_configured_safety_margin(monkeypatch) -> None:
    monkeypatch.setattr(
        "training.rl.hermes_workflow._request_token_count",
        lambda _tokenizer, kwargs: sum(
            len(str(row.get("content", ""))) for row in kwargs["messages"]
        ),
    )
    agent = SimpleNamespace(
        tools=[],
        max_iterations=6,
        _handle_max_iterations=lambda _messages, _count: "upstream-summary",
    )
    agent._build_api_kwargs = lambda messages, tools_for_api=None: {
        "messages": messages,
        "max_tokens": 1536,
    }
    runtime_errors = []
    controller = ContextBudgetController(
        tokenizer=object(),
        engine_max_tokens=4096,
        finalization_ratio=0.80,
        safety_margin_tokens=256,
        runtime_error_callback=runtime_errors.append,
    )
    controller.install(agent)

    try:
        agent._build_api_kwargs([{"role": "user", "content": "x" * 3800}])
    except RuntimeError as error:
        assert "safe target 3840" in str(error)
    else:
        raise AssertionError("request without a 256-token safety margin must fail closed")

    assert agent.max_iterations == 0
    assert runtime_errors == ["context_budget_guard_failed"]


def test_context_budget_does_not_mislabel_request_builder_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        "training.rl.hermes_workflow._request_token_count",
        lambda *_args, **_kwargs: 1,
    )
    agent = SimpleNamespace(
        tools=[],
        max_iterations=6,
        _handle_max_iterations=lambda _messages, _count: "upstream-summary",
    )

    def broken_builder(_messages, tools_for_api=None):
        raise RuntimeError("transport configuration failed")

    agent._build_api_kwargs = broken_builder
    runtime_errors = []
    controller = ContextBudgetController(
        tokenizer=object(),
        engine_max_tokens=4096,
        finalization_ratio=0.80,
        safety_margin_tokens=256,
        runtime_error_callback=runtime_errors.append,
    )
    controller.install(agent)

    try:
        agent._build_api_kwargs([{"role": "user", "content": "hello"}])
    except RuntimeError as error:
        assert str(error) == "transport configuration failed"
    else:
        raise AssertionError("request builder failure must propagate")

    assert controller.telemetry.counter_failures == 0
    assert runtime_errors == []


def test_context_runtime_error_is_a_reward_hard_gate() -> None:
    runtime = FrozenTaskEnvironment({"tools": [], "documents": []}, max_tool_calls=1)
    runtime.record_runtime_error("context_budget_provider_rejection")

    result = evaluate_reward_v2(
        final_answer="A provider error string must not count as an answer.",
        trace=runtime.trace,
        verifier={"family": "function_calling", "expected_calls": []},
        max_tool_calls=1,
    )

    assert result.total == -1.0
    assert result.hard_gate_triggered is True
    assert "context_budget_provider_rejection" in result.violations


def test_fixture_environment_enforces_tool_budget() -> None:
    environment = {
        "tools": [
            {
                "name": "lookup_value",
                "description": "Look up a frozen value.",
                "capability": "function_call",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            }
        ],
        "documents": [],
    }
    fixture = {
        "routes": [
            {
                "name": "lookup_value",
                "arguments": {"key": "alpha"},
                "result": "42",
            }
        ]
    }
    runtime = FrozenTaskEnvironment(environment, fixture, max_tool_calls=1)

    first = json.loads(asyncio.run(runtime.execute("lookup_value", {"key": "alpha"})))
    second = json.loads(asyncio.run(runtime.execute("lookup_value", {"key": "alpha"})))

    assert first == {
        "content": "42",
        "fixture_match": True,
        "ok": True,
        "tool": "lookup_value",
    }
    assert second == {"error": "tool_call_budget_exhausted", "max_tool_calls": 1}
    assert len(runtime.trace.tool_calls) == 2
    assert runtime.trace.invalid_tool_calls == 1


def test_fixture_environment_rejects_unmatched_arguments() -> None:
    environment = {
        "tools": [
            {
                "name": "lookup_value",
                "description": "Look up a frozen value.",
                "capability": "function_call",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            }
        ],
        "documents": [],
    }
    fixture = {
        "routes": [
            {
                "name": "lookup_value",
                "arguments": {"key": "alpha"},
                "result": "42",
            }
        ]
    }
    runtime = FrozenTaskEnvironment(environment, fixture, max_tool_calls=2)

    result = json.loads(asyncio.run(runtime.execute("lookup_value", {"key": "beta"})))

    assert result == {
        "error": "fixture_route_not_found",
        "fixture_match": False,
        "ok": False,
        "tool": "lookup_value",
    }
    assert runtime.trace.invalid_tool_calls == 1
    assert runtime.trace.error_codes == ["fixture_route_not_found"]


def test_replay_search_accepts_rewritten_query_without_changing_frozen_results() -> None:
    environment = {
        "tools": [
            {
                "name": "web_search",
                "description": "Search a frozen Web snapshot.",
                "capability": "replay_search",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
        "documents": [],
    }
    fixture = {
        "routes": [
            {
                "name": "web_search",
                "arguments": {"query": "通信原理 公开资料"},
                "result": {
                    "query": "通信原理 公开资料",
                    "results": [{"source_id": "web:1", "url": "https://example.edu/1"}],
                },
            }
        ]
    }
    runtime = FrozenTaskEnvironment(environment, fixture, max_tool_calls=2)

    result = json.loads(asyncio.run(runtime.execute("web_search", {"query": "通信原理 期末资料"})))

    assert result["query"] == "通信原理 期末资料"
    assert result["results"] == [{"source_id": "web:1", "url": "https://example.edu/1"}]
    assert runtime.trace.invalid_tool_calls == 0


def test_knowledge_read_preserves_exact_permission_denial_fixture() -> None:
    environment = {
        "tools": [
            {
                "name": "knowledge_read",
                "description": "Read one source.",
                "capability": "knowledge_read",
                "parameters": {
                    "type": "object",
                    "properties": {"source_id": {"type": "string"}},
                    "required": ["source_id"],
                },
            }
        ],
        "documents": [],
    }
    fixture = {
        "routes": [
            {
                "name": "knowledge_read",
                "arguments": {"source_id": "private:42"},
                "result": {"error": "permission_denied", "source_id": "private:42"},
            }
        ]
    }
    runtime = FrozenTaskEnvironment(environment, fixture, max_tool_calls=2)

    result = json.loads(asyncio.run(runtime.execute("knowledge_read", {"source_id": "private:42"})))

    assert result == {"error": "permission_denied", "source_id": "private:42"}
    assert runtime.trace.invalid_tool_calls == 0


def test_grounded_reward_uses_hidden_evidence_and_valid_citation() -> None:
    source_id = "src-0123456789ab"
    environment = {
        "tools": [
            {
                "name": "knowledge_search_test",
                "description": "Search the frozen corpus.",
                "capability": "knowledge_search",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "knowledge_read_test",
                "description": "Read a frozen source.",
                "capability": "knowledge_read",
                "parameters": {
                    "type": "object",
                    "properties": {"source_id": {"type": "string"}},
                    "required": ["source_id"],
                },
            },
        ],
        "documents": [
            {
                "source_id": source_id,
                "title": "Frozen evidence",
                "text": "The verified answer is forty two.",
            }
        ],
    }
    runtime = FrozenTaskEnvironment(environment, max_tool_calls=4)
    asyncio.run(runtime.execute("knowledge_search_test", {"query": "verified answer"}))
    asyncio.run(runtime.execute("knowledge_read_test", {"source_id": source_id}))

    result = evaluate_reward_v2(
        final_answer=f"The answer is forty two [{source_id}].",
        trace=runtime.trace,
        verifier={
            "family": "evidence_grounding",
            "expected_answers": ["forty two"],
            "gold_source_ids": [source_id],
            "citations_required": True,
        },
        max_tool_calls=4,
    )

    assert result.task_success == 1.0
    assert result.evidence == 1.0
    assert result.citation == 1.0
    assert result.tool_quality == 1.0
    assert not result.violations
    assert result.total > 0.8


def test_read_requires_source_to_be_discovered_by_search() -> None:
    source_id = "src-0123456789ab"
    environment = {
        "tools": [
            {
                "name": "knowledge_search_test",
                "description": "Search the frozen corpus.",
                "capability": "knowledge_search",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "knowledge_read_test",
                "description": "Read a frozen source.",
                "capability": "knowledge_read",
                "parameters": {"type": "object", "properties": {}},
            },
        ],
        "documents": [{"source_id": source_id, "title": "Evidence", "text": "forty two"}],
    }
    runtime = FrozenTaskEnvironment(environment, max_tool_calls=3)

    rejected = json.loads(asyncio.run(runtime.execute("knowledge_read_test", {"source_id": source_id})))
    asyncio.run(runtime.execute("knowledge_search_test", {"query": "forty two"}))
    accepted = json.loads(asyncio.run(runtime.execute("knowledge_read_test", {"source_id": source_id})))

    assert rejected == {"error": "source_not_discovered", "source_id": source_id}
    assert accepted["source_id"] == source_id
    assert runtime.trace.read_source_ids == {source_id}
    assert runtime.trace.error_codes == ["source_not_discovered"]


def test_search_returns_compact_previews_and_preserves_full_read() -> None:
    source_id = "src-0123456789ab"
    text = "evidence " * 100
    environment = {
        "tools": [
            {
                "name": "knowledge_search_test",
                "description": "Search the frozen corpus.",
                "capability": "knowledge_search",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "knowledge_read_test",
                "description": "Read a frozen source.",
                "capability": "knowledge_read",
                "parameters": {"type": "object", "properties": {}},
            },
        ],
        "documents": [{"source_id": source_id, "title": "Evidence", "text": text}],
    }
    runtime = FrozenTaskEnvironment(environment, max_tool_calls=2)

    search = json.loads(
        asyncio.run(runtime.execute("knowledge_search_test", {"query": "evidence"}))
    )
    read = json.loads(
        asyncio.run(runtime.execute("knowledge_read_test", {"source_id": source_id}))
    )

    assert len(search["results"][0]["snippet"]) == SEARCH_SNIPPET_CHARS
    assert read["text"] == text


def test_function_reward_requires_a_final_answer() -> None:
    runtime = FrozenTaskEnvironment(
        {
            "tools": [
                {
                    "name": "lookup_value",
                    "description": "Look up a frozen value.",
                    "capability": "function_call",
                    "parameters": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                        "required": ["key"],
                    },
                }
            ],
            "documents": [],
        },
        {
            "routes": [
                {
                    "name": "lookup_value",
                    "arguments": {"key": "alpha"},
                    "result": "42",
                }
            ]
        },
        max_tool_calls=2,
    )
    asyncio.run(runtime.execute("lookup_value", {"key": "alpha"}))

    result = evaluate_reward_v2(
        final_answer="",
        trace=runtime.trace,
        verifier={
            "family": "function_calling",
            "expected_calls": [{"name": "lookup_value", "arguments": {"key": "alpha"}}],
            "expected_answers": ["42"],
        },
        max_tool_calls=2,
    )

    assert result.function_call_quality == 1.0
    assert result.answer_quality == -1.0
    assert result.task_success == 0.4
    assert result.total <= 0.0
    assert "empty_final_answer" in result.violations


def test_invalid_citation_is_a_hard_gate() -> None:
    source_id = "src-0123456789ab"
    runtime = FrozenTaskEnvironment(
        {"tools": [], "documents": []},
        max_tool_calls=1,
    )
    runtime.trace.tool_calls.append({"name": "knowledge_read", "arguments": {}})
    runtime.trace.read_source_ids.add(source_id)

    result = evaluate_reward_v2(
        final_answer="forty two [src-ffffffffffff]",
        trace=runtime.trace,
        verifier={
            "family": "evidence_grounding",
            "expected_answers": ["forty two"],
            "gold_source_ids": [source_id],
            "citations_required": True,
        },
        max_tool_calls=1,
    )

    assert result.total == -1.0
    assert result.hard_gate_triggered is True
    assert "invalid_citation" in result.violations


def test_toolace_parser_keeps_all_tool_rounds_and_only_the_final_answer() -> None:
    conversations = [
        {"from": "user", "value": "Plan an outdoor party."},
        {"from": "assistant", "value": '[weather(city="Paris")]'},
        {"from": "tool", "value": '[{"name":"weather","results":{"dry":true}}]'},
        {"from": "assistant", "value": "[layout(tables=5)]"},
        {"from": "tool", "value": '[{"name":"layout","results":{"status":"ok"}}]'},
        {"from": "assistant", "value": "The weather is dry and the layout is ready."},
    ]

    parsed = parse_toolace_trajectory(conversations, ["weather", "layout"])

    assert parsed is not None
    user_request, calls, responses, final, reference_model_turns = parsed
    assert user_request == "Plan an outdoor party."
    assert [call["original_name"] for call in calls] == ["weather", "layout"]
    assert [response["original_name"] for response in responses] == ["weather", "layout"]
    assert final == "The weather is dry and the layout is ready."
    assert reference_model_turns == 3
