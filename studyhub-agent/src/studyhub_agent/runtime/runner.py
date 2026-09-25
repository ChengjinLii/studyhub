from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

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
from studyhub_agent.contracts.prompts import PromptRegistry
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.environments.base import Environment
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


class EpisodeRunner:
    """The one agent loop shared by data generation, RL rollouts and evaluation."""

    def __init__(self, *, prompts: PromptRegistry, tokenizer_revision: str, count_tokens: TokenCounter) -> None:
        self._prompts = prompts
        self._tokenizer_revision = tokenizer_revision
        self._count_tokens = count_tokens

    def contract_for(self, spec: EpisodeSpec, tools: Sequence[ToolSpec]) -> str:
        return contract_hash(
            ContractInputs(
                system_prompt=self._prompts.get(spec.system_prompt),
                finalize_prompt=self._prompts.get(spec.finalize_prompt),
                tools=tuple(tools),
                thinking=spec.thinking,
                tokenizer_revision=self._tokenizer_revision,
                max_context_tokens=spec.budget.max_context_tokens,
                max_new_tokens=spec.budget.max_new_tokens,
            )
        )

    def run(self, spec: EpisodeSpec, environment: Environment, policy: PolicyClient) -> Episode:
        tools = select_tools(spec.tool_names)
        contract = self.contract_for(spec, tools)
        environment.reset(spec)
        progress = _Progress(
            messages=[
                Message(role="system", content=self._prompts.get(spec.system_prompt).text),
                Message(role="user", content=spec.user_message),
            ]
        )
        outcome = self._loop(spec, environment, policy, tools, progress)
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
        )

    def _loop(
        self,
        spec: EpisodeSpec,
        environment: Environment,
        policy: PolicyClient,
        tools: tuple[ToolSpec, ...],
        progress: _Progress,
    ) -> tuple[Termination, FailureOwner, str | None, str | None]:
        budget = spec.budget
        for turn_index in range(budget.max_turns):
            if turn_index == budget.max_turns - 1 and turn_index > 0:
                progress.messages.append(
                    Message(role="tool", name="runtime_feedback", content=self._prompts.get(spec.finalize_prompt).text)
                )
            token_count = self._count_tokens(progress.messages, tools, spec.thinking)
            if token_count > budget.max_context_tokens - budget.max_new_tokens:
                return Termination.CONTEXT_BUDGET, FailureOwner.MODEL, None, None
            try:
                turn = policy.step(
                    progress.messages,
                    tools,
                    thinking=spec.thinking,
                    sampling=spec.sampling,
                    max_new_tokens=budget.max_new_tokens,
                )
            except PolicyInfraError as exc:
                return Termination.INFRA_ERROR, FailureOwner.INFRA, None, str(exc)
            turn = _relabel(turn, turn_index)
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
                progress.messages.append(Message(role="assistant", content=turn.content))
                return Termination.FINAL_ANSWER, FailureOwner.NONE, turn.content, None
            if progress.tool_calls_used + len(turn.tool_calls) > budget.max_tool_calls:
                return Termination.TOOL_BUDGET, FailureOwner.MODEL, None, None
            progress.messages.append(Message(role="assistant", content=turn.content, tool_calls=turn.tool_calls))
            progress.tool_calls_used += len(turn.tool_calls)
            for call in turn.tool_calls:
                try:
                    observation = environment.execute(call)
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
