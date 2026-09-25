from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from studyhub_agent.contracts.prompts import FINALIZE_PROMPT_KEY, SYSTEM_PROMPT_KEY


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolCall(_Frozen):
    call_id: str
    name: str
    arguments: dict[str, Any]


class Message(_Frozen):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


class Sampling(_Frozen):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    seed: int | None = None


class Budget(_Frozen):
    max_turns: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=16, ge=1)
    max_parse_errors: int = Field(default=2, ge=0)
    max_context_tokens: int = Field(default=16384, ge=1)
    max_new_tokens: int = Field(default=2048, ge=1)

    @model_validator(mode="after")
    def _prompt_room(self) -> Budget:
        if self.max_new_tokens >= self.max_context_tokens:
            raise ValueError("max_new_tokens must be smaller than max_context_tokens")
        return self


class Principal(_Frozen):
    principal_id: str
    purchased_material_ids: frozenset[int] = frozenset()
    owned_material_ids: frozenset[int] = frozenset()
    is_admin: bool = False


class EpisodeSpec(_Frozen):
    episode_id: str
    task_id: str
    user_message: str
    principal: Principal
    system_prompt: str = SYSTEM_PROMPT_KEY
    finalize_prompt: str = FINALIZE_PROMPT_KEY
    tool_names: tuple[str, ...]
    thinking: bool = False
    budget: Budget = Budget()
    sampling: Sampling = Sampling()
    metadata: dict[str, str] = Field(default_factory=dict)


class TurnKind(StrEnum):
    TOOL_CALLS = "tool_calls"
    FINAL = "final"
    PARSE_ERROR = "parse_error"


class AssistantTurn(_Frozen):
    kind: TurnKind
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    raw_text: str
    canonical_text: str
    parse_error: str | None = None
    prompt_token_ids: tuple[int, ...] = ()
    completion_token_ids: tuple[int, ...] = ()
    completion_logprobs: tuple[float, ...] = ()
    non_canonical: bool = False
    server_parse_mismatch: bool = False
    finish_reason: str | None = None
    latency_ms: float = 0.0


class Observation(_Frozen):
    call_id: str
    name: str
    ok: bool
    payload: dict[str, Any]
    error_code: str | None = None


class Termination(StrEnum):
    FINAL_ANSWER = "final_answer"
    MAX_TURNS = "max_turns"
    TOOL_BUDGET = "tool_budget"
    PARSE_ERROR_BUDGET = "parse_error_budget"
    CONTEXT_BUDGET = "context_budget"
    ENV_ERROR = "env_error"
    INFRA_ERROR = "infra_error"


class FailureOwner(StrEnum):
    NONE = "none"
    MODEL = "model"
    ENV = "env"
    INFRA = "infra"


class Episode(_Frozen):
    spec: EpisodeSpec
    contract_hash: str
    messages: tuple[Message, ...]
    turns: tuple[AssistantTurn, ...]
    observations: tuple[Observation, ...]
    termination: Termination
    failure_owner: FailureOwner
    final_answer: str | None = None
    error_detail: str | None = None
    environment_trace: dict[str, Any] = Field(default_factory=dict)
