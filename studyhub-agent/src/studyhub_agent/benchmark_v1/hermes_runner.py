from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.environment import ReplayableAgentEnvironment
from studyhub_agent.benchmark_v1.schema import BenchmarkTask

BENCHMARK_SYSTEM_PROMPT = """You are StudyHub Agent in an isolated benchmark environment.
Choose actions autonomously: answer directly when tools are unnecessary, abstain when evidence is insufficient,
or use the listed StudyHub tools when evidence or a state transition is required. Use only observations returned
inside this task. Never access production services, credentials, the host filesystem, shell, or an unlisted tool.
Cite each factual source-backed claim as [source_id] after reading or fetching that source. Respect ACL denials,
recover from transient failures without inventing results, and stop when the request is fully supported."""


def _disabled_tool_search_config():
    from tools.tool_search import ToolSearchConfig

    return ToolSearchConfig.from_raw({"enabled": "off"})


def _install_benchmark_prompt(agent: Any, constraints: list[str]) -> None:
    constraint_text = "\n".join(f"- {value}" for value in constraints)
    prompt = f"{BENCHMARK_SYSTEM_PROMPT}\n\nTask constraints:\n{constraint_text}"

    def build_prompt(system_message: str | None = None) -> str:
        parts = [prompt]
        if system_message and system_message.strip() not in {prompt, BENCHMARK_SYSTEM_PROMPT}:
            parts.append(system_message.strip())
        return "\n\n".join(parts)

    agent._build_system_prompt = build_prompt
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    agent.ephemeral_system_prompt = None


def _install_request_audit(agent: Any) -> None:
    """Record prompt cardinality and hashes without retaining prompt text."""

    original_build = agent._build_api_kwargs
    records: list[dict[str, Any]] = []

    def audited_build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        api_kwargs = original_build(*args, **kwargs)
        messages = list(api_kwargs.get("messages") or [])
        system_contents = [
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        ]
        joined = "\n\n".join(system_contents)
        records.append(
            {
                "request_index": len(records),
                "message_count": len(messages),
                "system_message_count": len(system_contents),
                "benchmark_prompt_occurrences": joined.count(BENCHMARK_SYSTEM_PROMPT),
                "system_prompt_sha256": hashlib.sha256(joined.encode()).hexdigest(),
                "tool_schema_count": len(api_kwargs.get("tools") or []),
            }
        )
        return api_kwargs

    agent._build_api_kwargs = audited_build
    agent._studyhub_request_audit = records


class BenchmarkHermesRunner:
    """Thin benchmark adapter around the pinned, unmodified Hermes loop."""

    def __init__(
        self,
        *,
        hidden_root: str | Path,
        hermes_checkout: str | Path,
        tokenizer_path: str | Path,
        base_url: str,
        api_key: str,
        model: str = "default",
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_completion_tokens: int = 1536,
        context_finalization_ratio: float = 0.80,
        context_safety_margin_tokens: int = 768,
    ) -> None:
        self.hidden_root = Path(hidden_root).resolve()
        self.hermes_checkout = Path(hermes_checkout).resolve()
        self.tokenizer_path = str(Path(tokenizer_path).resolve())
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_completion_tokens = max_completion_tokens
        self.context_finalization_ratio = context_finalization_ratio
        self.context_safety_margin_tokens = context_safety_margin_tokens
        self._tokenizer: Any | None = None

    def _load_runtime(self):
        checkout = str(self.hermes_checkout)
        if checkout not in sys.path:
            sys.path.insert(0, checkout)
        from agent import relay_runtime
        from run_agent import AIAgent
        from tools import tool_search
        from tools.registry import registry

        profile_key = relay_runtime.current_profile_key()
        with relay_runtime.HOST_REGISTRY._lock:
            relay_runtime.HOST_REGISTRY._hosts.setdefault(
                profile_key,
                relay_runtime.NoopRelayRuntime(
                    profile_key=profile_key,
                    reason="disabled for StudyHub benchmark rollout",
                ),
            )
        tool_search.load_config = _disabled_tool_search_config
        return AIAgent, registry

    def _load_tokenizer(self):
        if self._tokenizer is None:
            from areal.utils.hf_utils import load_hf_tokenizer

            self._tokenizer = load_hf_tokenizer(self.tokenizer_path)
        return self._tokenizer

    async def run(self, task_row: dict[str, Any], *, sample_seed: int) -> dict[str, Any]:
        from training.rl.hermes_workflow import (
            ContextBudgetController,
            _enable_training_tool_guardrails,
            _training_runtime_metadata,
        )

        task = BenchmarkTask.from_dict(task_row)
        environment = ReplayableAgentEnvironment.from_root(self.hidden_root, task.split, task.task_id)
        AIAgent, registry = self._load_runtime()
        toolset = f"studyhub-benchmark-{task.task_id}-{uuid.uuid4().hex[:10]}"
        installed: list[str] = []
        agent: Any | None = None
        result: dict[str, Any] = {}
        started = time.monotonic()
        for schema in environment.tool_schemas:
            name = str(schema["name"])

            async def handler(arguments: dict[str, Any], _name: str = name, **_kwargs: Any) -> str:
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    arguments = {}
                return await environment.execute(_name, arguments)

            registry.register(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                is_async=True,
                description=str(schema["description"]),
                max_result_size_chars=12_000,
            )
            if registry.get_entry(name) is None:
                raise RuntimeError(f"Hermes rejected benchmark tool registration: {name}")
            installed.append(name)

        try:
            budget = task.budget
            agent = AIAgent(
                base_url=self.base_url,
                api_key=self.api_key,
                provider="custom",
                api_mode="chat_completions",
                model=self.model,
                max_iterations=int(budget["max_model_turns"]),
                enabled_toolsets=[toolset],
                save_trajectories=False,
                quiet_mode=True,
                tool_progress_mode="off",
                session_id=f"benchmark-{task.task_id}-{sample_seed}-{uuid.uuid4().hex[:8]}",
                max_tokens=min(self.max_completion_tokens, int(budget["max_context_tokens"]) // 2),
                request_overrides={
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "seed": sample_seed,
                },
                platform="batch",
                skip_context_files=True,
                load_soul_identity=False,
                skip_memory=True,
                skip_background_review=True,
                session_db=None,
                checkpoints_enabled=False,
            )
            agent._task_completion_guidance = False
            agent._parallel_tool_call_guidance = False
            agent._execution_guidance = False
            agent._environment_probe = False
            agent._disable_streaming = True
            _install_benchmark_prompt(agent, list(task.hard_constraints))
            _enable_training_tool_guardrails(agent, installed)
            ContextBudgetController(
                tokenizer=self._load_tokenizer(),
                engine_max_tokens=int(budget["max_context_tokens"]),
                finalization_ratio=self.context_finalization_ratio,
                safety_margin_tokens=min(
                    self.context_safety_margin_tokens,
                    max(128, int(budget["max_context_tokens"]) // 4),
                ),
                runtime_error_callback=environment.record_runtime_error,
            ).install(agent)
            _install_request_audit(agent)
            result = await asyncio.to_thread(
                agent.run_conversation,
                task.user_request,
                task_id=task.task_id,
            )
            if not isinstance(result, dict):
                result = {"final_response": str(result), "messages": []}
        finally:
            for name in installed:
                registry.deregister(name)

        final_answer = str(result.get("final_response") or "")
        if "exceeds max_total_tokens" in final_answer:
            environment.record_runtime_error("context_budget_provider_rejection")
            final_answer = ""
        return {
            "final_answer": final_answer,
            "messages": list(result.get("messages") or []),
            "trace": environment.trace.to_dict(),
            "final_state": environment.state_snapshot(),
            "runtime": {
                **(_training_runtime_metadata(agent) if agent is not None else {}),
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "sample_seed": sample_seed,
                "request_audit": list(getattr(agent, "_studyhub_request_audit", [])) if agent is not None else [],
            },
        }
