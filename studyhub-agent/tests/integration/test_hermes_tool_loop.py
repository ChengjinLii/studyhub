from __future__ import annotations

import json
import subprocess
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_SECRET = "hermes-integration-fixture-secret"


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
