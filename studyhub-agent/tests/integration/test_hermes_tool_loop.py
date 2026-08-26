from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from studyhub_agent.adapters.collective_memory import FixtureCollectiveMemoryReader
from studyhub_agent.adapters.personal_memory import InMemoryPersonalMemoryProvider
from studyhub_agent.adapters.rag import RagExperimentKnowledgeRetriever
from studyhub_agent.adapters.web import FixtureWebFetchProvider, FixtureWebSearchProvider, GuardedWebProviders
from studyhub_agent.guardrails.budget import BudgetState
from studyhub_agent.guardrails.permissions import PermissionContext
from studyhub_agent.guardrails.web_security import WebSecurityPolicy
from studyhub_agent.integrations import HermesToolBridge
from studyhub_agent.runtime import AgentIdentity, TaskSpec
from studyhub_agent.tools.factory import ToolServices, build_tool_registry
from studyhub_agent.tools.registry import ToolExecutionContext
from tests.fakes.openai_server import ScriptedOpenAIServer, ToolTurn
from training.rl.hermes_workflow import StudyHubHermesWorkflow

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_SECRET = "hermes-integration-fixture-secret"
PROXY_ENV = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


def _prepare_hermes_test_runtime(monkeypatch) -> None:
    checkout = ROOT / ".vendor/hermes-agent"
    if not (checkout / "run_agent.py").is_file():
        pytest.skip("pinned Hermes checkout is not installed")
    monkeypatch.syspath_prepend(str(checkout))
    for key in PROXY_ENV:
        monkeypatch.delenv(key, raising=False)


def _resolver(hostname: str) -> list[str]:
    if hostname in {"docs.example.edu", "standards.example.org"}:
        return ["93.184.216.34"]
    return ["127.0.0.1"]


def _context(case_id: str, allowed_tools: list[str], services: ToolServices) -> tuple[ToolExecutionContext, object]:
    identity = AgentIdentity.from_raw_user_id(
        "fixture-user",
        session_id=f"session-{case_id}",
        environment="eval",
        identity_secret=IDENTITY_SECRET,
    )
    task = TaskSpec(
        task_id=case_id,
        family="long_horizon",
        difficulty="medium",
        user_request="fixture integration request",
        environment_seed=7200,
        allowed_tools=allowed_tools,
        max_steps=10,
        max_tool_calls=max(1, len(allowed_tools) + 1),
    )
    namespace = identity.personal_memory_namespace(case_id=case_id, seed=task.environment_seed)
    services.personal_memory.add(namespace, "用户偏好按题型刷真题。", {"kind": "study_preference"})
    context = ToolExecutionContext(
        identity=identity,
        task=task,
        permissions=PermissionContext(principal_id=identity.principal_id),
        budget=BudgetState(max_steps=task.max_steps, max_tool_calls=task.max_tool_calls),
        memory_namespace=namespace,
    )
    return context, build_tool_registry(services)


def _services() -> ToolServices:
    return ToolServices(
        knowledge=RagExperimentKnowledgeRetriever.from_jsonl(ROOT / "fixtures/rag/chunks.jsonl"),
        web=GuardedWebProviders(
            search_provider=FixtureWebSearchProvider.from_json(ROOT / "fixtures/web/search.json"),
            fetch_provider=FixtureWebFetchProvider.from_json(ROOT / "fixtures/web/pages.json"),
            policy=WebSecurityPolicy(max_redirects=2, max_response_bytes=10_000),
            resolver=_resolver,
        ),
        personal_memory=InMemoryPersonalMemoryProvider(),
        collective_memory=FixtureCollectiveMemoryReader.from_json(ROOT / "fixtures/memory/collective.json"),
    )


def _decode_tool_payload(content: str) -> dict:
    if content.startswith("<untrusted_tool_result"):
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end < start:
            raise AssertionError("Hermes untrusted-result envelope contains no JSON payload")
        content = content[start : end + 1]
    return json.loads(content)


def test_hermes_checkout_matches_clean_unpatched_upstream() -> None:
    lock = json.loads((ROOT / "integrations/hermes/upstream.lock.json").read_text(encoding="utf-8"))
    checkout = ROOT / ".vendor/hermes-agent"

    assert set(lock) == {"repository", "commit"}
    assert subprocess.check_output(["git", "-C", checkout, "rev-parse", "HEAD"], text=True).strip() == lock["commit"]
    assert subprocess.check_output(["git", "-C", checkout, "status", "--porcelain"], text=True).strip() == ""
    setup = (ROOT / "scripts/setup-hermes.sh").read_text(encoding="utf-8")
    assert "git apply" not in setup
    assert "patches/" not in setup


def test_real_hermes_runs_all_fixture_tool_combinations(monkeypatch, tmp_path) -> None:
    _prepare_hermes_test_runtime(monkeypatch)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    (tmp_path / "hermes-home").mkdir()
    (tmp_path / "hermes-home/config.yaml").write_text(
        "tools:\n  tool_search:\n    enabled: off\n",
        encoding="utf-8",
    )

    from run_agent import AIAgent

    scenarios = {
        "rag": [ToolTurn("knowledge_search", {"query": "通信原理 真题", "limit": 3})],
        "web": [ToolTurn("web_search", {"query": "通信原理 复习", "limit": 3})],
        "memory": [ToolTurn("personal_memory_search", {"query": "刷题 偏好", "limit": 3})],
        "rag_memory": [
            ToolTurn("knowledge_search", {"query": "通信原理 真题", "limit": 3}),
            ToolTurn("personal_memory_search", {"query": "刷题 偏好", "limit": 3}),
        ],
        "rag_web_memory": [
            ToolTurn("knowledge_search", {"query": "通信原理 真题", "limit": 3}),
            ToolTurn("web_search", {"query": "通信原理 复习", "limit": 3}),
            ToolTurn("personal_memory_search", {"query": "刷题 偏好", "limit": 3}),
        ],
    }

    for scenario, turns in scenarios.items():
        services = _services()
        allowed = list(dict.fromkeys(turn.name for turn in turns))
        context, registry = _context(f"hermes-{scenario}", allowed, services)
        with ScriptedOpenAIServer(turns, f"fixture-final:{scenario}") as server:
            with HermesToolBridge(registry, context):
                agent = AIAgent(
                    base_url=server.base_url,
                    api_key="fixture-key",
                    provider="custom",
                    api_mode="chat_completions",
                    model="fake-studyhub",
                    max_iterations=8,
                    enabled_toolsets=["studyhub"],
                    quiet_mode=True,
                    ephemeral_system_prompt="Use the available StudyHub tools, then answer.",
                    session_id=f"fixture-{scenario}",
                    skip_context_files=True,
                    load_soul_identity=False,
                    skip_memory=True,
                    skip_background_review=True,
                    checkpoints_enabled=False,
                )
                agent._disable_streaming = True
                answer = agent.chat("Run the scripted fixture scenario.")

        assert answer == f"fixture-final:{scenario}"
        assert len(server.requests) == len(turns) + 1
        assert len(server.tool_result_messages) >= len(turns)
        assert all(message.get("content") for message in server.tool_result_messages)
        tool_payloads = [_decode_tool_payload(message["content"]) for message in server.tool_result_messages]
        assert all("error" not in payload for payload in tool_payloads)

    from tools.registry import registry as hermes_registry

    assert hermes_registry.get_entry("web_search").toolset == "web"


def test_training_workflow_runs_real_hermes_against_frozen_tool(monkeypatch, tmp_path) -> None:
    _prepare_hermes_test_runtime(monkeypatch)
    monkeypatch.setattr(
        StudyHubHermesWorkflow,
        "_load_tokenizer",
        lambda _self: object(),
    )
    monkeypatch.setattr(
        "training.rl.hermes_workflow._request_token_count",
        lambda _tokenizer, _kwargs: 256,
    )
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        "tools:\n  tool_search:\n    enabled: off\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    task_id = "fixture-training-workflow"
    environment_root = tmp_path / "rl-data"
    for name in ("environments", "fixtures", "verifiers"):
        (environment_root / name).mkdir(parents=True)
    tool_schema = {
        "name": "fixture_training_lookup",
        "description": "Look up one deterministic fixture value.",
        "capability": "function_call",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    }
    (environment_root / "environments" / f"{task_id}.json").write_text(
        json.dumps({"tools": [tool_schema], "documents": []}),
        encoding="utf-8",
    )
    expected_call = {"name": tool_schema["name"], "arguments": {"key": "alpha"}}
    (environment_root / "fixtures" / f"{task_id}.json").write_text(
        json.dumps({"routes": [{**expected_call, "result": "42"}]}),
        encoding="utf-8",
    )
    (environment_root / "verifiers" / "validation.jsonl").write_text(
        json.dumps(
            {
                "verifier_id": "verifier-fixture",
                "family": "function_calling",
                "expected_calls": [expected_call],
                "expected_answers": ["42"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    workflow = StudyHubHermesWorkflow(
        environment_root=str(environment_root),
        verifier_root=str(environment_root / "verifiers"),
        hermes_checkout=str(ROOT / ".vendor/hermes-agent"),
        reward_artifact_root=str(tmp_path / "rewards"),
        max_turns=4,
        max_tokens=128,
    )
    data = {
        "task_id": task_id,
        "user_request": "Look up alpha, then answer with the observed value.",
        "max_steps": 4,
        "max_tool_calls": 2,
        "metadata": {"verifier_id": "verifier-fixture"},
        "verifier": {},
    }

    with ScriptedOpenAIServer(
        [ToolTurn(tool_schema["name"], {"key": "alpha"})],
        "42",
    ) as server:
        reward = asyncio.run(
            workflow.run(
                data,
                base_url=server.base_url,
                api_key="fixture-session-key",
            )
        )

    assert reward > 0.8
    assert len(server.requests) == 2
    reward_rows = (tmp_path / "rewards/reward-v2.jsonl").read_text(encoding="utf-8").splitlines()
    recorded = json.loads(reward_rows[0])
    assert recorded["task_id"] == task_id
    assert recorded["rollout_group_id"]
    assert recorded["rollout_id"]
    assert recorded["final_answer_empty"] is False
    assert recorded["trace"]["tool_calls"] == 1
    assert recorded["trace"]["invalid_tool_calls"] == 0
    assert recorded["reward"]["task_success"] == 1.0
    assert recorded["reward"]["answer_quality"] == 1.0
    assert recorded["reward"]["function_call_quality"] == 1.0
