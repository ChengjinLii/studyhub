from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from studyhub_agent.integrations.hermes_registry import HermesRegistryOverlay
from training.rl.dataset_v3 import budget_for, validate_public_task
from training.rl.environment_v3 import TrainingTaskEnvironmentV3
from training.rl.hermes_workflow import (
    _AREAL_CHAT_TEMPLATE_METADATA_KEY,
    _AREAL_DISABLE_THINKING_VALUE,
    _CONTEXT_LIMIT_PATTERN,
    ContextBudgetController,
    StudyHubHermesWorkflow,
    _load_verifier_store,
    _training_runtime_metadata,
)
from training.rl.reward_v3 import INFRA_STATUS, RewardV3Result, evaluate_reward_v3

SYSTEM_PROMPT_V3 = """You are StudyHub Agent in an isolated post-training environment.
Solve the user's goal autonomously using only the tools exposed for this task. Respect ACL,
privacy, state and tool budgets. Search before reading unknown sources, cite factual claims as
[source_id] only after reading or fetching that source, recover from retryable failures, and
stop when the requested outcome is complete. Multiple valid tool paths may exist. Never access
the network, filesystem, shell, credentials, hidden verifier, or production StudyHub services."""


def decode_public_task_row(data: dict[str, Any]) -> dict[str, Any]:
    """Decode the stable JSON transport used by the AReaL DatasetDict."""

    if "task_json" not in data:
        return dict(data)
    task = json.loads(str(data["task_json"]))
    if not isinstance(task, dict):
        raise ValueError("AReaL task_json must decode to an object")
    if str(data.get("task_id", "")) != str(task.get("task_id", "")):
        raise ValueError("AReaL task transport ID mismatch")
    return task


def _install_v3_system_prompt(agent: Any) -> None:
    def build_prompt(system_message: str | None = None) -> str:
        parts = [SYSTEM_PROMPT_V3]
        if system_message and system_message.strip() != SYSTEM_PROMPT_V3:
            parts.append(system_message.strip())
        return "\n\n".join(parts)

    agent._build_system_prompt = build_prompt
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    agent.ephemeral_system_prompt = None


def _enable_v3_guardrails(agent: Any, tool_names: list[str], mutating_tools: set[str]) -> None:
    from agent.tool_guardrails import ToolCallGuardrailConfig, ToolCallGuardrailController

    all_tools = set(tool_names)
    agent._tool_guardrails = ToolCallGuardrailController(
        ToolCallGuardrailConfig(
            warnings_enabled=True,
            hard_stop_enabled=True,
            exact_failure_block_after=3,
            same_tool_failure_halt_after=5,
            no_progress_block_after=3,
            idempotent_tools=frozenset(all_tools - mutating_tools),
            mutating_tools=frozenset(mutating_tools),
        )
    )
    agent._tool_guardrail_halt_decision = None


class StudyHubHermesWorkflowV3(StudyHubHermesWorkflow):
    """Hermes policy loop over v3 open-path tasks and Reward v3."""

    def __init__(self, *, enable_thinking: bool | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.enable_thinking = enable_thinking

    def _request_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {"temperature": self.temperature, "top_p": self.top_p}
        if self.enable_thinking is False:
            overrides["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            # The SDK consumes extra_body; this existing proxy contract survives HTTP.
            overrides["metadata"] = {_AREAL_CHAT_TEMPLATE_METADATA_KEY: _AREAL_DISABLE_THINKING_VALUE}
        return overrides

    async def run(self, data: dict[str, Any], **extra_kwargs: Any) -> float:
        data = decode_public_task_row(data)
        validate_public_task(data)
        task_id = str(data["task_id"])
        metadata = dict(data.get("metadata", {}))
        verifier_id = str(metadata.get("verifier_id", ""))
        verifier = _load_verifier_store(self.verifier_root).get(verifier_id)
        if verifier is None:
            raise KeyError(f"hidden verifier not found: {verifier_id}")
        if verifier.get("schema_version") != "studyhub.reward-verifier.v3":
            raise ValueError(f"invalid Reward v3 verifier: {verifier_id}")

        environment = TrainingTaskEnvironmentV3.from_root(self.environment_root, task_id)
        base_url = extra_kwargs.get("base_url") or os.getenv("OPENAI_BASE_URL")
        api_key = extra_kwargs.get("api_key") or os.getenv("OPENAI_API_KEY")
        if not base_url or not api_key:
            raise RuntimeError("AReaL did not provide the rollout gateway URL and session API key")

        AIAgent, registry = self._load_hermes()
        budget = budget_for(str(data["budget_tier"]))
        toolset = f"studyhub-rl-v3-{task_id}"
        overlay = HermesRegistryOverlay(registry)
        hermes_runtime: dict[str, Any] = {}
        for schema in environment.tool_schemas:
            name = schema["name"]

            async def handler(arguments: dict[str, Any], _name: str = name, **_kwargs: Any) -> str:
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    arguments = {}
                return await environment.execute(_name, arguments)

            try:
                overlay.install(
                    name=name,
                    toolset=toolset,
                    schema=schema,
                    handler=handler,
                )
            except BaseException:
                overlay.restore()
                raise

        final_answer = ""
        try:
            agent = AIAgent(
                base_url=str(base_url),
                api_key=str(api_key),
                provider="custom",
                api_mode="chat_completions",
                model="default",
                max_iterations=min(self.max_turns, budget["max_model_turns"]),
                enabled_toolsets=[toolset],
                save_trajectories=False,
                quiet_mode=True,
                tool_progress_mode="off",
                session_id=f"{task_id}-{uuid.uuid4().hex[:12]}",
                max_tokens=self.max_tokens,
                request_overrides=self._request_overrides(),
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
            _install_v3_system_prompt(agent)
            _enable_v3_guardrails(
                agent,
                [schema["name"] for schema in environment.tool_schemas],
                environment.mutating_tools,
            )
            ContextBudgetController(
                tokenizer=self._load_tokenizer(),
                engine_max_tokens=self.engine_max_tokens,
                finalization_ratio=self.context_finalization_ratio,
                safety_margin_tokens=self.context_safety_margin_tokens,
                runtime_error_callback=environment.record_runtime_error,
            ).install(agent)
            final_answer = str(await asyncio.to_thread(agent.chat, str(data["goal"])))
            hermes_runtime = _training_runtime_metadata(agent)
        finally:
            overlay.restore()

        if _CONTEXT_LIMIT_PATTERN in final_answer:
            environment.record_runtime_error("context_budget_provider_rejection")
            final_answer = ""

        trace = environment.trace_dict()
        result = evaluate_reward_v3(
            final_answer=final_answer,
            trace=trace,
            final_state=environment.state_snapshot(),
            verifier=verifier,
        )
        self._record_reward_v3(
            data=data,
            metadata=metadata,
            verifier=verifier,
            final_answer=final_answer,
            trace=trace,
            final_state=environment.state_snapshot(),
            result=result,
            session_api_key=str(api_key),
            hermes_runtime=hermes_runtime,
        )
        if result.status == INFRA_STATUS:
            # The pinned AReaL workflow drops exceptions/None trajectories; with
            # complete-group enforcement this excludes Infra from GRPO advantages.
            raise RuntimeError(f"Reward v3 excluded infrastructure failure for {task_id}")
        return result.total

    def _record_reward_v3(
        self,
        *,
        data: dict[str, Any],
        metadata: dict[str, Any],
        verifier: dict[str, Any],
        final_answer: str,
        trace: dict[str, Any],
        final_state: dict[str, Any],
        result: RewardV3Result,
        session_api_key: str,
        hermes_runtime: dict[str, Any],
    ) -> None:
        self.reward_artifact_root.mkdir(parents=True, exist_ok=True)
        path = self.reward_artifact_root / "reward-v3.jsonl"
        task_id = str(data["task_id"])
        rollout_id = hashlib.sha256(session_api_key.encode()).hexdigest()[:20]
        rollout_group_id = hashlib.sha256(f"{self.experiment_name}:{self.trial_name}:{task_id}".encode()).hexdigest()[
            :20
        ]
        state_sha = hashlib.sha256(json.dumps(final_state, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        row = {
            "schema_version": "studyhub.reward-log.v3",
            "recorded_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "experiment_name": self.experiment_name,
            "trial_name": self.trial_name,
            "run_kind": self.run_kind,
            "seed": self.seed,
            "task_id": task_id,
            "task_family": verifier["family"],
            "source_dataset": metadata.get("source_dataset"),
            "source_group_id": metadata.get("source_group_id"),
            "split": metadata.get("split"),
            "rollout_group_id": rollout_group_id,
            "rollout_id": rollout_id,
            "final_answer_sha256": hashlib.sha256(final_answer.encode()).hexdigest(),
            "final_answer_length": len(final_answer),
            "final_answer_empty": not final_answer.strip(),
            "final_state_sha256": state_sha,
            "budget_tier": data["budget_tier"],
            "max_steps": budget_for(str(data["budget_tier"]))["max_model_turns"],
            "max_tool_calls": budget_for(str(data["budget_tier"]))["max_tool_calls"],
            "trace": {
                "tool_calls": len(trace.get("tool_calls", [])),
                "tool_names": [call.get("name") for call in trace.get("tool_calls", [])],
                "policy_errors": list(trace.get("policy_errors", [])),
                "environment_errors": list(trace.get("environment_errors", [])),
                "runtime_errors": list(trace.get("runtime_errors", [])),
                "read_sources": list(trace.get("read_source_ids", [])),
                "state_changes": len(trace.get("state_changes", [])),
                "hermes": hermes_runtime,
            },
            "reward": result.to_dict(),
        }
        with path.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
