from __future__ import annotations

import asyncio
import fcntl
import functools
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
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

CONTEXT_FINALIZATION_GUIDANCE = (
    "[StudyHub runtime: the remaining model-turn or context budget permits only "
    "a final answer. Do not call more "
    "tools. Use only the observations already shown and provide the best supported "
    "final answer now. Do not show analysis. Keep the answer under 300 words and "
    "include required [source_id] citations.]"
)
_CONTEXT_LIMIT_PATTERN = "exceeds max_total_tokens"
_AREAL_CHAT_TEMPLATE_METADATA_KEY = "studyhub_chat_template"
_AREAL_DISABLE_THINKING_VALUE = "disable_thinking_v1"


def _request_token_count(tokenizer: Any, api_kwargs: dict[str, Any]) -> int:
    """Render the request with the same HF path used by the pinned AReaL proxy."""

    from areal.experimental.openai.client import (
        _align_tools_with_sglang,
        _parse_tool_call_arguments,
    )
    from areal.utils.hf_utils import apply_chat_template

    messages = api_kwargs.get("messages")
    if not isinstance(messages, list):
        raise TypeError("StudyHub context guard requires chat-completions messages")
    normalized_messages = _parse_tool_call_arguments(messages)
    tools = api_kwargs.get("tools")
    aligned_tools = _align_tools_with_sglang(list(tools)) if tools else None
    extra_body = api_kwargs.get("extra_body")
    chat_template_kwargs = (
        extra_body.get("chat_template_kwargs", {})
        if isinstance(extra_body, dict)
        else {}
    )
    token_ids = apply_chat_template(
        tokenizer,
        normalized_messages,
        tools=aligned_tools,
        add_generation_prompt=True,
        tokenize=True,
        **chat_template_kwargs,
    )
    return len(token_ids)


def _append_context_finalization_guidance(messages: list[dict[str, Any]]) -> None:
    if any(CONTEXT_FINALIZATION_GUIDANCE in str(row.get("content", "")) for row in messages):
        return
    for row in reversed(messages):
        if row.get("role") == "tool":
            row["content"] = f"{row.get('content', '')}\n\n{CONTEXT_FINALIZATION_GUIDANCE}"
            return
    for row in reversed(messages):
        if row.get("role") == "user":
            row["content"] = f"{row.get('content', '')}\n\n{CONTEXT_FINALIZATION_GUIDANCE}"
            return
    messages.append({"role": "user", "content": CONTEXT_FINALIZATION_GUIDANCE})


def _head_tail(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    head = max(1, (limit - 48) // 2)
    tail = max(1, limit - 48 - head)
    return f"{value[:head]}\n...[context compacted]...\n{value[-tail:]}"


def _compact_tool_content(content: Any, limit: int = 480) -> str:
    raw = str(content or "")
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None
    preserved: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key in (
            "source_id",
            "title",
            "citation",
            "tool",
            "ok",
            "error",
            "fixture_match",
            "query",
        ):
            if key in payload:
                preserved[key] = payload[key]
        body = next(
            (
                str(payload[key])
                for key in ("text", "content", "result", "results")
                if key in payload
            ),
            raw,
        )
    else:
        body = raw
    preserved["observation_excerpt"] = _head_tail(body, limit)
    preserved["_studyhub_context_compacted"] = {
        "original_chars": len(raw),
        "sha256": digest,
    }
    return json.dumps(preserved, ensure_ascii=False, sort_keys=True)


@dataclass(slots=True)
class ContextBudgetTelemetry:
    engine_max_tokens: int
    finalization_threshold_tokens: int
    safety_margin_tokens: int
    exact_counter_calls: int = 0
    max_pre_guard_prompt_tokens: int = 0
    max_sent_prompt_tokens: int = 0
    forced_final_count: int = 0
    forced_final_reasons: list[str] = field(default_factory=list)
    finalization_thinking_disabled: bool = False
    compacted_tool_messages: int = 0
    compacted_tool_chars: int = 0
    dropped_tool_exchanges: int = 0
    counter_failures: int = 0
    guard_failures: int = 0
    final_completion_cap_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_max_tokens": self.engine_max_tokens,
            "finalization_threshold_tokens": self.finalization_threshold_tokens,
            "safety_margin_tokens": self.safety_margin_tokens,
            "exact_counter_calls": self.exact_counter_calls,
            "max_pre_guard_prompt_tokens": self.max_pre_guard_prompt_tokens,
            "max_sent_prompt_tokens": self.max_sent_prompt_tokens,
            "forced_final": self.forced_final_count > 0,
            "forced_final_count": self.forced_final_count,
            "forced_final_reasons": list(self.forced_final_reasons),
            "finalization_thinking_disabled": self.finalization_thinking_disabled,
            "compacted_tool_messages": self.compacted_tool_messages,
            "compacted_tool_chars": self.compacted_tool_chars,
            "dropped_tool_exchanges": self.dropped_tool_exchanges,
            "counter_failures": self.counter_failures,
            "guard_failures": self.guard_failures,
            "final_completion_cap_tokens": self.final_completion_cap_tokens,
        }


class ContextBudgetController:
    """Force a final Hermes turn before AReaL's exported-token hard limit."""

    def __init__(
        self,
        *,
        tokenizer: Any,
        engine_max_tokens: int,
        finalization_ratio: float,
        safety_margin_tokens: int,
        runtime_error_callback: Any,
    ) -> None:
        if engine_max_tokens < 512:
            raise ValueError("engine_max_tokens must leave room for an agent turn")
        if not 0.5 <= finalization_ratio < 1.0:
            raise ValueError("context finalization ratio must be in [0.5, 1.0)")
        if not 64 <= safety_margin_tokens < engine_max_tokens // 2:
            raise ValueError("invalid context safety margin")
        threshold = int(engine_max_tokens * finalization_ratio)
        if threshold >= engine_max_tokens - safety_margin_tokens:
            raise ValueError("context finalization threshold must precede the safety margin")
        self.tokenizer = tokenizer
        self.runtime_error_callback = runtime_error_callback
        self.telemetry = ContextBudgetTelemetry(
            engine_max_tokens=engine_max_tokens,
            finalization_threshold_tokens=threshold,
            safety_margin_tokens=safety_margin_tokens,
        )
        self._forced_final = False
        self._fail_closed = False

    def install(self, agent: Any) -> None:
        original_build = agent._build_api_kwargs
        original_summary = agent._handle_max_iterations
        agent._studyhub_context_budget = self

        def guarded_build(
            api_messages: list[dict[str, Any]],
            tools_for_api: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any]:
            if tools_for_api is None:
                api_kwargs = original_build(api_messages)
            else:
                api_kwargs = original_build(
                    api_messages,
                    tools_for_api=tools_for_api,
                )
            try:
                before = self._count(api_kwargs)
            except Exception:
                self.telemetry.counter_failures += 1
                self.runtime_error_callback("context_budget_counter_failed")
                self._fail_closed = True
                agent.max_iterations = 0
                raise

            on_last_model_turn = self._on_last_model_turn(agent)
            should_force_final = (
                self._forced_final
                or on_last_model_turn
                or before >= self.telemetry.finalization_threshold_tokens
            )
            if not should_force_final:
                self.telemetry.max_sent_prompt_tokens = max(
                    self.telemetry.max_sent_prompt_tokens,
                    before,
                )
                return api_kwargs

            if not self._forced_final:
                self._forced_final = True
                self.telemetry.forced_final_count += 1
                reason = "model_turn_budget" if on_last_model_turn else "context_threshold"
                self.telemetry.forced_final_reasons.append(reason)
            api_kwargs.pop("tools", None)
            api_kwargs.pop("tool_choice", None)
            api_kwargs.pop("parallel_tool_calls", None)
            # Do not spend the final-answer reserve in an unclosed think block.
            extra_body = api_kwargs.get("extra_body")
            if not isinstance(extra_body, dict):
                extra_body = {}
                api_kwargs["extra_body"] = extra_body
            chat_template_kwargs = extra_body.get("chat_template_kwargs")
            if not isinstance(chat_template_kwargs, dict):
                chat_template_kwargs = {}
                extra_body["chat_template_kwargs"] = chat_template_kwargs
            chat_template_kwargs["enable_thinking"] = False
            metadata = api_kwargs.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                api_kwargs["metadata"] = metadata
            # The OpenAI SDK consumes its own `extra_body` before forwarding
            # the HTTP request. This supported metadata field survives the
            # proxy boundary and is translated back by the process-local
            # AReaL runtime shim.
            metadata[_AREAL_CHAT_TEMPLATE_METADATA_KEY] = (
                _AREAL_DISABLE_THINKING_VALUE
            )
            self.telemetry.finalization_thinking_disabled = True
            messages = api_kwargs["messages"]
            _append_context_finalization_guidance(messages)
            target = (
                self.telemetry.engine_max_tokens
                - self.telemetry.safety_margin_tokens
            )
            sent = self._count(api_kwargs)
            if sent > target:
                sent = self._compact_observations(api_kwargs, target)
            if sent > target:
                sent = self._drop_oldest_tool_exchanges(api_kwargs, target)
            if sent > target:
                self.telemetry.guard_failures += 1
                self.runtime_error_callback("context_budget_guard_failed")
                self._fail_closed = True
                agent.max_iterations = 0
                raise RuntimeError(
                    f"StudyHub context guard could not reduce {sent} prompt tokens "
                    f"to the safe target {target}"
                )

            remaining = self.telemetry.engine_max_tokens - sent
            cap_key = (
                "max_completion_tokens"
                if "max_completion_tokens" in api_kwargs
                else "max_tokens"
            )
            existing_cap = api_kwargs.get(cap_key)
            try:
                requested_cap = int(existing_cap)
            except (TypeError, ValueError):
                requested_cap = remaining
            final_cap = max(
                1,
                min(
                    requested_cap,
                    remaining,
                    self.telemetry.safety_margin_tokens,
                ),
            )
            api_kwargs[cap_key] = final_cap
            self.telemetry.final_completion_cap_tokens = final_cap
            self.telemetry.max_sent_prompt_tokens = max(
                self.telemetry.max_sent_prompt_tokens,
                sent,
            )
            return api_kwargs

        def guarded_summary(messages: list[dict[str, Any]], api_call_count: int) -> str:
            if self._forced_final or self._fail_closed:
                self.telemetry.guard_failures += 1
                self.runtime_error_callback("context_budget_finalization_failed")
                return ""
            return original_summary(messages, api_call_count)

        agent._build_api_kwargs = guarded_build
        agent._handle_max_iterations = guarded_summary

    @staticmethod
    def _on_last_model_turn(agent: Any) -> bool:
        budget = getattr(agent, "iteration_budget", None)
        remaining = getattr(budget, "remaining", None)
        return isinstance(remaining, int) and not isinstance(remaining, bool) and remaining <= 0

    def _count(self, api_kwargs: dict[str, Any]) -> int:
        self.telemetry.exact_counter_calls += 1
        count = _request_token_count(self.tokenizer, api_kwargs)
        self.telemetry.max_pre_guard_prompt_tokens = max(
            self.telemetry.max_pre_guard_prompt_tokens,
            count,
        )
        return count

    def _compact_observations(
        self,
        api_kwargs: dict[str, Any],
        target: int,
    ) -> int:
        messages = api_kwargs["messages"]
        count = self._count(api_kwargs)
        for row in messages:
            if row.get("role") != "tool":
                continue
            original = str(row.get("content", ""))
            compacted = _compact_tool_content(original)
            if len(compacted) >= len(original):
                continue
            row["content"] = compacted
            self.telemetry.compacted_tool_messages += 1
            self.telemetry.compacted_tool_chars += len(original) - len(compacted)
            count = self._count(api_kwargs)
            if count <= target:
                break
        return count

    def _drop_oldest_tool_exchanges(
        self,
        api_kwargs: dict[str, Any],
        target: int,
    ) -> int:
        messages = api_kwargs["messages"]
        count = self._count(api_kwargs)
        while count > target:
            removed = False
            for index, row in enumerate(messages):
                if row.get("role") != "assistant" or not row.get("tool_calls"):
                    continue
                end = index + 1
                while end < len(messages) and messages[end].get("role") == "tool":
                    end += 1
                del messages[index:end]
                self.telemetry.dropped_tool_exchanges += 1
                self.runtime_error_callback("context_budget_emergency_compaction")
                removed = True
                break
            if not removed:
                break
            count = self._count(api_kwargs)
        return count


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
    context_budget = getattr(agent, "_studyhub_context_budget", None)
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
        "context_budget": (
            context_budget.telemetry.to_dict() if context_budget is not None else None
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
        tokenizer_path: str = "",
        engine_max_tokens: int = 4096,
        context_finalization_ratio: float = 0.80,
        context_safety_margin_tokens: int = 768,
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
        self.tokenizer_path = str(Path(tokenizer_path).resolve()) if tokenizer_path else ""
        self.engine_max_tokens = int(engine_max_tokens)
        self.context_finalization_ratio = float(context_finalization_ratio)
        self.context_safety_margin_tokens = int(context_safety_margin_tokens)
        self.temperature = temperature
        self.top_p = top_p
        _load_verifier_store(self.verifier_root)

    def _load_tokenizer(self):
        if not self.tokenizer_path:
            raise ValueError("tokenizer_path is required for exact context budgeting")
        from areal.utils.hf_utils import load_hf_tokenizer

        return load_hf_tokenizer(self.tokenizer_path)

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
            ContextBudgetController(
                tokenizer=self._load_tokenizer(),
                engine_max_tokens=self.engine_max_tokens,
                finalization_ratio=self.context_finalization_ratio,
                safety_margin_tokens=self.context_safety_margin_tokens,
                runtime_error_callback=environment.record_runtime_error,
            ).install(agent)
            final_answer = str(await asyncio.to_thread(agent.chat, str(data["user_request"])))
            hermes_runtime = _training_runtime_metadata(agent)
        finally:
            for name in installed:
                registry.deregister(name)

        if _CONTEXT_LIMIT_PATTERN in final_answer:
            environment.record_runtime_error("context_budget_provider_rejection")
            final_answer = ""

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
                "runtime_errors": list(environment.trace.runtime_errors),
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
