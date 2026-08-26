from __future__ import annotations

import asyncio
import fcntl
import functools
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from training.rl.frozen_environment import FrozenTaskEnvironment
from training.rl.reward_v2 import RewardV2Result, evaluate_reward_v2

SYSTEM_PROMPT = """You are StudyHub Agent in an isolated training environment.
Use only the tools exposed for this task. Never access the network, filesystem, shell,
credentials, or production StudyHub services. For corpus tasks, search before reading,
read the necessary evidence, and cite every used source as [source_id]. Stop when the
answer is supported; do not invent observations or citations."""


def _disabled_hermes_tool_search_config():
    from tools.tool_search import ToolSearchConfig

    return ToolSearchConfig.from_raw({"enabled": "off"})


def _install_training_system_prompt(agent: Any) -> None:
    """Keep the Hermes loop while removing unrelated interactive-host guidance."""

    def build_prompt(system_message: str | None = None) -> str:
        parts = [SYSTEM_PROMPT]
        if system_message and system_message.strip() != SYSTEM_PROMPT:
            parts.append(system_message.strip())
        return "\n\n".join(parts)

    agent._build_system_prompt = build_prompt
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    # Hermes appends this field after `_build_system_prompt`. The training
    # prompt is already supplied by the replacement builder above, so keeping
    # an ephemeral copy would duplicate the policy-visible system message.
    agent.ephemeral_system_prompt = None


def _enable_training_tool_guardrails(agent: Any, tool_names: list[str]) -> None:
    """Apply stricter Hermes loop stops only inside frozen RL rollouts."""

    from agent.tool_guardrails import (
        ToolCallGuardrailConfig,
        ToolCallGuardrailController,
    )

    agent._tool_guardrails = ToolCallGuardrailController(
        ToolCallGuardrailConfig(
            warnings_enabled=True,
            hard_stop_enabled=True,
            exact_failure_block_after=3,
            same_tool_failure_halt_after=5,
            no_progress_block_after=3,
            idempotent_tools=frozenset(tool_names),
            mutating_tools=frozenset(),
        )
    )
    agent._tool_guardrail_halt_decision = None


def _training_runtime_metadata(agent: Any) -> dict[str, Any]:
    halt_decision = getattr(agent, "_tool_guardrail_halt_decision", None)
    context_compressor = getattr(agent, "context_compressor", None)
    return {
        "guardrail_halt": (
            halt_decision.to_metadata() if halt_decision is not None else None
        ),
        "api_calls": int(getattr(agent, "_api_call_count", 0) or 0),
        "input_tokens": int(getattr(agent, "session_input_tokens", 0) or 0),
        "output_tokens": int(getattr(agent, "session_output_tokens", 0) or 0),
        "prompt_tokens": int(getattr(agent, "session_prompt_tokens", 0) or 0),
        "completion_tokens": int(
            getattr(agent, "session_completion_tokens", 0) or 0
        ),
        "total_tokens": int(getattr(agent, "session_total_tokens", 0) or 0),
        "last_prompt_tokens": int(
            getattr(context_compressor, "last_prompt_tokens", 0) or 0
        ),
    }


@functools.lru_cache(maxsize=8)
def _load_verifier_store(verifier_root: Path) -> dict[str, dict[str, Any]]:
    verifiers = {}
    for path in sorted(verifier_root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                verifier_id = str(row["verifier_id"])
                if verifier_id in verifiers:
                    raise ValueError(f"duplicate verifier_id: {verifier_id}")
                verifiers[verifier_id] = row
    if not verifiers:
        raise FileNotFoundError(f"no verifier JSONL files under {verifier_root}")
    return verifiers


class StudyHubHermesWorkflow:
    """AReaL-compatible workflow that keeps Hermes as the rollout harness."""

    def __init__(
        self,
        *,
        environment_root: str,
        verifier_root: str,
        hermes_checkout: str,
        reward_artifact_root: str,
        experiment_name: str = "studyhub-open-grpo",
        trial_name: str = "unscoped",
        run_kind: str = "train",
        seed: int = 0,
        max_turns: int = 10,
        max_tokens: int = 1536,
        max_completion_tokens: int | None = None,
        temperature: float = 1.0,
        top_p: float = 1.0,
        **_: Any,
    ) -> None:
        self.environment_root = Path(environment_root).resolve()
        self.verifier_root = Path(verifier_root).resolve()
        self.hermes_checkout = Path(hermes_checkout).resolve()
        self.reward_artifact_root = Path(reward_artifact_root).resolve()
        self.experiment_name = experiment_name
        self.trial_name = trial_name
        self.run_kind = run_kind
        self.seed = seed
        self.max_turns = max_turns
        self.max_tokens = max_completion_tokens or max_tokens
        self.temperature = temperature
        self.top_p = top_p
        _load_verifier_store(self.verifier_root)

    def _load_hermes(self):
        checkout = str(self.hermes_checkout)
        if checkout not in sys.path:
            sys.path.insert(0, checkout)
        from agent import relay_runtime
        from run_agent import AIAgent
        from tools import tool_search
        from tools.registry import registry

        # Frozen RL rollouts intentionally expose only per-task tools. Keep the
        # optional Relay/plugin runtime out of this isolated execution path.
        profile_key = relay_runtime.current_profile_key()
        with relay_runtime.HOST_REGISTRY._lock:
            relay_runtime.HOST_REGISTRY._hosts.setdefault(
                profile_key,
                relay_runtime.NoopRelayRuntime(
                    profile_key=profile_key,
                    reason="disabled for StudyHub frozen RL rollout",
                ),
            )

        # Each frozen task exposes only a few schemas. Direct disclosure keeps
        # the learned action space aligned with the environment and verifier.
        tool_search.load_config = _disabled_hermes_tool_search_config

        return AIAgent, registry

    async def run(self, data: dict[str, Any], **extra_kwargs: Any) -> float:
        task_id = str(data["task_id"])
        metadata = dict(data.get("metadata", {}))
        if data.get("verifier"):
            raise RuntimeError(f"public task {task_id} contains verifier data")
        verifier_id = str(metadata.get("verifier_id", ""))
        verifier = _load_verifier_store(self.verifier_root).get(verifier_id)
        if verifier is None:
            raise KeyError(f"hidden verifier not found: {verifier_id}")
        max_tool_calls = int(data["max_tool_calls"])
        environment = FrozenTaskEnvironment.from_root(
            self.environment_root,
            task_id,
            max_tool_calls=max_tool_calls,
        )
        base_url = extra_kwargs.get("base_url") or os.getenv("OPENAI_BASE_URL")
        api_key = extra_kwargs.get("api_key") or os.getenv("OPENAI_API_KEY")
        if not base_url or not api_key:
            raise RuntimeError("AReaL did not provide the rollout gateway URL and session API key")

        AIAgent, registry = self._load_hermes()
        toolset = f"studyhub-rl-{task_id}"
        installed = []
        hermes_runtime: dict[str, Any] = {}
        for schema in environment.tool_schemas:
            name = schema["name"]

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
                description=schema["description"],
                max_result_size_chars=12_000,
            )
            if registry.get_entry(name) is None:
                raise RuntimeError(f"Hermes rejected isolated tool registration: {name}")
            installed.append(name)

        try:
            agent = AIAgent(
                base_url=str(base_url),
                api_key=str(api_key),
                provider="custom",
                api_mode="chat_completions",
                model="default",
                max_iterations=min(self.max_turns, int(data["max_steps"])),
                enabled_toolsets=[toolset],
                save_trajectories=False,
                quiet_mode=True,
                tool_progress_mode="off",
                session_id=f"{task_id}-{uuid.uuid4().hex[:12]}",
                max_tokens=self.max_tokens,
                request_overrides={"temperature": self.temperature, "top_p": self.top_p},
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
            _install_training_system_prompt(agent)
            _enable_training_tool_guardrails(agent, installed)
            final_answer = str(await asyncio.to_thread(agent.chat, str(data["user_request"])))
            hermes_runtime = _training_runtime_metadata(agent)
        finally:
            for name in installed:
                registry.deregister(name)

        result = evaluate_reward_v2(
            final_answer=final_answer,
            trace=environment.trace,
            verifier=verifier,
            max_tool_calls=max_tool_calls,
        )
        self._record_reward(
            data=data,
            metadata=metadata,
            verifier=verifier,
            final_answer=final_answer,
            environment=environment,
            result=result,
            session_api_key=str(api_key),
            hermes_runtime=hermes_runtime,
        )
        return result.total

    def _record_reward(
        self,
        *,
        data: dict[str, Any],
        metadata: dict[str, Any],
        verifier: dict[str, Any],
        final_answer: str,
        environment: FrozenTaskEnvironment,
        result: RewardV2Result,
        session_api_key: str,
        hermes_runtime: dict[str, Any],
    ) -> None:
        self.reward_artifact_root.mkdir(parents=True, exist_ok=True)
        path = self.reward_artifact_root / "reward-v2.jsonl"
        task_id = str(data["task_id"])
        rollout_id = hashlib.sha256(session_api_key.encode()).hexdigest()[:20]
        rollout_group_id = hashlib.sha256(f"{self.experiment_name}:{self.trial_name}:{task_id}".encode()).hexdigest()[
            :20
        ]
        row = {
            "schema_version": "studyhub.reward-log.v2",
            "recorded_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "experiment_name": self.experiment_name,
            "trial_name": self.trial_name,
            "run_kind": self.run_kind,
            "seed": self.seed,
            "task_id": task_id,
            "task_family": verifier["family"],
            "source_dataset": metadata.get("source_dataset"),
            "source_group_id": metadata.get("group_id"),
            "split": metadata.get("split"),
            "rollout_group_id": rollout_group_id,
            "rollout_id": rollout_id,
            "final_answer_sha256": hashlib.sha256(final_answer.encode()).hexdigest(),
            "final_answer_length": len(final_answer),
            "final_answer_empty": not final_answer.strip(),
            "max_steps": int(data["max_steps"]),
            "max_tool_calls": int(data["max_tool_calls"]),
            "trace": {
                "tool_calls": len(environment.trace.tool_calls),
                "tool_names": [row["name"] for row in environment.trace.tool_calls],
                "invalid_tool_calls": environment.trace.invalid_tool_calls,
                "error_codes": list(environment.trace.error_codes),
                "search_results": len(environment.trace.search_result_ids),
                "read_sources": sorted(environment.trace.read_source_ids),
                "hermes": hermes_runtime,
            },
            "reward": result.to_dict(),
        }
        with path.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
