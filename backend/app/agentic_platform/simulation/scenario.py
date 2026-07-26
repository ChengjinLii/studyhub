"""Explicit fixture scenarios for snapshot and simulated environments."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.observation import Observation
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.state import StateDelta
from app.agentic_platform.domain.transition import ExecutionError, VerifierResult

from .snapshot import EnvironmentSnapshot


class ScenarioAction(DomainModel):
    """A fixture outcome for one caller-selected decision.

    It is intentionally a test/simulation artifact, not a production action
    whitelist.  Live environments receive decisions through an injected
    executor and do not consult this list.
    """

    action_id: str = Field(min_length=1, max_length=128)
    expected_decision: AgentDecision
    state_delta: StateDelta = Field(default_factory=StateDelta)
    observation: Observation | None = None
    verifier_result: VerifierResult | None = None
    reward_facts: RewardFacts = Field(default_factory=RewardFacts)
    error: ExecutionError | None = None

    @field_validator("action_id")
    @classmethod
    def reject_blank_action_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @property
    def decision_hash(self) -> str:
        return canonical_hash(self.expected_decision)


class ScenarioSpec(DomainModel):
    """A starting snapshot plus optional, deterministic fixture outcomes."""

    schema_version: str = "1.0"
    scenario_id: str = Field(min_length=1, max_length=128)
    initial_snapshot: EnvironmentSnapshot
    actions: list[ScenarioAction] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=1_024)

    @field_validator("scenario_id", "description")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_action_ids(self) -> "ScenarioSpec":
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("scenario action IDs must be unique")
        return self
