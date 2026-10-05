from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType

from studyhub_agent.contracts.architecture import Accept, Architecture, Continue, RunContext
from studyhub_agent.contracts.episode import (
    AssistantTurn,
    Episode,
    EpisodeSpec,
    FailureOwner,
    Message,
    Observation,
    Termination,
    ToolCall,
    TurnKind,
)
from studyhub_agent.contracts.fingerprint import ContractInputs, contract_hash
from studyhub_agent.contracts.prompts import PromptRegistry, PromptTemplate
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.environments.base import Environment, EnvironmentInfraError
from studyhub_agent.runtime.architecture import ReactArchitecture
from studyhub_agent.runtime.policy import PolicyClient, PolicyInfraError
from studyhub_agent.tools.specs import select_tools

TokenCounter = Callable[[Sequence[Message], Sequence[ToolSpec], bool], int]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _feedback(payload: dict) -> Message:
    return Message(role="tool", name="runtime_feedback", content=_json(payload))


@dataclass
class _Progress:
    messages: list[Message]
    turns: list[AssistantTurn] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    tool_calls_used: int = 0
    parse_errors: int = 0
    policy_key: str = "small"
    trace: dict = field(default_factory=dict)


class EpisodeRunner:
    """The one agent loop shared by data generation, RL rollouts and evaluation."""

    def __init__(self, *, prompts: PromptRegistry, tokenizer_revision: str, count_tokens: TokenCounter) -> None:
        self._prompts = prompts
        self._tokenizer_revision = tokenizer_revision
        self._count_tokens = count_tokens

    def contract_for(
        self,
        spec: EpisodeSpec,
        tools: Sequence[ToolSpec],
        *,
        architecture: Architecture | None = None,
        models: Mapping[str, str] | None = None,
        model_revisions: Mapping[str, str] | None = None,
    ) -> str:
        architecture = architecture if architecture is not None else ReactArchitecture()
        models, model_revisions = dict(models or {}), dict(model_revisions or {})
        policy_keys = {"small"} | models.keys() | model_revisions.keys()
        return contract_hash(
            ContractInputs(
                system_prompt=self._prompts.get(spec.system_prompt),
                finalize_prompt=self._prompts.get(spec.finalize_prompt),
                tools=tuple(tools),
                thinking=spec.thinking,
                tokenizer_revision=self._tokenizer_revision,
                max_context_tokens=spec.budget.max_context_tokens,
                max_new_tokens=spec.budget.max_new_tokens,
                max_turns=spec.budget.max_turns,
                max_tool_calls=spec.budget.max_tool_calls,
                max_parse_errors=spec.budget.max_parse_errors,
                architecture=f"{architecture.architecture_id}@{architecture.version}",
                architecture_prompts=tuple(self._prompts.get(key) for key in architecture.prompt_keys),
                architecture_parameters=dict(architecture.contract_parameters),
                models=tuple(
                    (key, models.get(key, ""), model_revisions.get(key, self._tokenizer_revision))
                    for key in sorted(policy_keys)
                ),
            )
        )

    def run(
        self,
        spec: EpisodeSpec,
        environment: Environment,
        policy: PolicyClient,
        *,
        architecture: Architecture | None = None,
        policies: Mapping[str, PolicyClient] | None = None,
        models: Mapping[str, str] | None = None,
        model_revisions: Mapping[str, str] | None = None,
        token_counters: Mapping[str, TokenCounter] | None = None,
    ) -> Episode:
        # Resolve against what this environment actually provides, not the global tool registry: a
        # tool name can be valid globally yet unavailable from a particular environment, and
        # prompting the model with a tool the environment can never execute is a configuration bug,
        # not something to discover only when the model tries to call it.
        tools = select_tools(spec.tool_names, environment.tool_specs())
        architecture = architecture if architecture is not None else ReactArchitecture()
        models, model_revisions = dict(models or {}), dict(model_revisions or {})
        policy_map = {"small": policy} if policies is None else dict(policies)
        if "small" not in policy_map:
            raise ValueError("policies must include the initial 'small' policy")
        required = getattr(architecture, "required_policy_keys", ("small",))
        if missing := set(required) - policy_map.keys():
            raise ValueError(f"architecture requires missing policies: {', '.join(sorted(missing))}")
        if models.keys() - policy_map.keys() or model_revisions.keys() - policy_map.keys():
            raise ValueError("models/model_revisions contain unknown policy keys")
        if policies is not None and (
            any(not models.get(key) for key in policy_map) or any(not model_revisions.get(key) for key in policy_map)
        ):
            raise ValueError("named policies require complete, non-empty models and model_revisions")
        resolved_revisions = {key: model_revisions.get(key, self._tokenizer_revision) for key in policy_map}
        counters = dict(token_counters or {})
        if counters.keys() - policy_map.keys():
            raise ValueError("token_counters contain unknown policy keys")
        for key, revision in resolved_revisions.items():
            if key not in counters:
                if revision != self._tokenizer_revision:
                    raise ValueError(f"policy {key!r} has a different tokenizer revision; supply token_counters")
                counters[key] = self._count_tokens
        contract = self.contract_for(
            spec, tools, architecture=architecture, models=models, model_revisions=resolved_revisions
        )
        prompts = MappingProxyType({key: self._prompts.get(key) for key in architecture.prompt_keys})
        environment.reset(spec)
        progress = _Progress(
            messages=[
                Message(role="system", content=self._prompts.get(spec.system_prompt).text),
                Message(role="user", content=spec.user_message),
            ]
        )
        progress.messages.extend(architecture.on_start(self._context(spec, progress, prompts)))
        outcome = self._loop(spec, environment, policy_map, tools, progress, architecture, prompts, models, counters)
        termination, owner, final_answer, detail = outcome
        return Episode(
            spec=spec,
            contract_hash=contract,
            messages=tuple(progress.messages),
            turns=tuple(progress.turns),
            observations=tuple(progress.observations),
            termination=termination,
            failure_owner=owner,
            final_answer=final_answer,
            error_detail=detail,
            environment_trace=environment.trace(),
            architecture=f"{architecture.architecture_id}@{architecture.version}",
            architecture_trace=deepcopy(progress.trace),
            models=models,
            model_revisions=resolved_revisions,
        )

    @staticmethod
    def _context(
        spec: EpisodeSpec,
        progress: _Progress,
        prompts: Mapping[str, PromptTemplate],
        *,
        count_tokens: Callable[[Sequence[Message]], int] | None = None,
    ) -> RunContext:
        # Hooks can modify their snapshot without rewriting the recorded trajectory/evidence.
        return RunContext(
            spec=spec.model_copy(deep=True),
            turns=tuple(turn.model_copy(deep=True) for turn in progress.turns),
            observations=tuple(observation.model_copy(deep=True) for observation in progress.observations),
            prompts=prompts,
            trace=progress.trace,
            policy_key=progress.policy_key,
            tool_calls_used=progress.tool_calls_used,
            parse_errors=progress.parse_errors,
            count_tokens=count_tokens,
        )

    def _loop(
        self,
        spec: EpisodeSpec,
        environment: Environment,
        policies: Mapping[str, PolicyClient],
        tools: tuple[ToolSpec, ...],
        progress: _Progress,
        architecture: Architecture,
        prompts: Mapping[str, PromptTemplate],
        models: Mapping[str, str],
        token_counters: Mapping[str, TokenCounter],
    ) -> tuple[Termination, FailureOwner, str | None, str | None]:
        budget = spec.budget
        for turn_index in range(budget.max_turns):
            if turn_index == budget.max_turns - 1:
                instruction = self._prompts.get(spec.finalize_prompt).text
                progress.messages.append(_feedback({"notice": "final_turn", "instruction": instruction}))
            view_counter = token_counters[progress.policy_key]
            ctx = self._context(
                spec,
                progress,
                prompts,
                count_tokens=lambda messages, counter=view_counter: counter(messages, tools, spec.thinking),
            )
            view = tuple(architecture.before_step(ctx, tuple(m.model_copy(deep=True) for m in progress.messages)))
            policy_key = architecture.select_policy(ctx)
            if policy_key not in policies:
                raise ValueError(f"architecture selected unknown policy {policy_key!r}")
            progress.policy_key = policy_key
            token_count = token_counters[policy_key](view, tools, spec.thinking)
            if token_count > budget.max_context_tokens - budget.max_new_tokens:
                # If this fires before the model ever got a turn, the budget was too small for the
                # prompt itself -- a configuration problem, not something the model did. Once at
                # least one turn has happened, the model's own output growing the context is on it.
                owner = FailureOwner.ENV if not progress.turns else FailureOwner.MODEL
                return Termination.CONTEXT_BUDGET, owner, None, None
            try:
                turn = policies[policy_key].step(
                    view,
                    tools,
                    thinking=spec.thinking,
                    sampling=spec.sampling,
                    max_new_tokens=budget.max_new_tokens,
                )
            except PolicyInfraError as exc:
                return Termination.INFRA_ERROR, FailureOwner.INFRA, None, str(exc)
            turn = _relabel(turn, turn_index).model_copy(
                update={"policy_key": policy_key, "model_id": models.get(policy_key, "")}
            )
            progress.turns.append(turn)
            if turn.kind is TurnKind.PARSE_ERROR:
                progress.parse_errors += 1
                progress.messages.append(Message(role="assistant", content=turn.raw_text))
                if progress.parse_errors > budget.max_parse_errors:
                    return Termination.PARSE_ERROR_BUDGET, FailureOwner.MODEL, None, turn.parse_error
                error_code = (turn.parse_error or "parse_error").split(":", 1)[0]
                progress.messages.append(_feedback({"error": error_code, "detail": turn.parse_error}))
                continue
            if turn.kind is TurnKind.FINAL:
                progress.messages.append(Message(role="assistant", content=turn.content, reasoning=turn.reasoning))
                decision = architecture.on_final(self._context(spec, progress, prompts), turn.model_copy(deep=True))
                if isinstance(decision, Accept):
                    return Termination.FINAL_ANSWER, FailureOwner.NONE, turn.content, None
                if not isinstance(decision, Continue):
                    raise TypeError("architecture.on_final must return Accept or Continue")
                progress.messages.extend(decision.feedback)
                progress.trace.setdefault("continues", []).append({"turn": turn_index, "reason": decision.reason})
                continue
            if progress.tool_calls_used + len(turn.tool_calls) > budget.max_tool_calls:
                # This turn is already recorded in progress.turns (appended above); keep messages
                # consistent with it by recording the assistant's tool-call message too, just
                # without executing any of the calls (no tool-response messages/observations).
                progress.messages.append(
                    Message(
                        role="assistant",
                        content=turn.content,
                        tool_calls=turn.tool_calls,
                        reasoning=turn.reasoning,
                    )
                )
                return Termination.TOOL_BUDGET, FailureOwner.MODEL, None, None
            progress.messages.append(
                Message(role="assistant", content=turn.content, tool_calls=turn.tool_calls, reasoning=turn.reasoning)
            )
            progress.tool_calls_used += len(turn.tool_calls)
            for call in turn.tool_calls:
                try:
                    observation = environment.execute(call)
                except EnvironmentInfraError as exc:
                    return Termination.INFRA_ERROR, FailureOwner.INFRA, None, str(exc)
                except Exception as exc:  # noqa: BLE001 - any tool crash is an environment failure
                    return Termination.ENV_ERROR, FailureOwner.ENV, None, f"{type(exc).__name__}: {exc}"
                progress.observations.append(observation)
                progress.messages.append(
                    Message(role="tool", tool_call_id=call.call_id, name=call.name, content=_json(observation.payload))
                )
        return Termination.MAX_TURNS, FailureOwner.MODEL, None, None


def _relabel(turn: AssistantTurn, turn_index: int) -> AssistantTurn:
    if not turn.tool_calls:
        return turn
    calls = tuple(
        ToolCall(call_id=f"t{turn_index}_c{index}", name=call.name, arguments=call.arguments)
        for index, call in enumerate(turn.tool_calls)
    )
    return turn.model_copy(update={"tool_calls": calls})
