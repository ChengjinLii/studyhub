"""Stable domain contracts shared by every agent runtime implementation.

The package intentionally contains no FastAPI, ORM, LangGraph, or model-provider
imports.  That keeps persisted runs and future training data independent of the
runtime that produced them.
"""

from ._base import DOMAIN_SCHEMA_VERSION, DomainModel
from .artifact import ArtifactKind, ArtifactRef
from .decision import AgentActionType, AgentDecision, AgentOutput, ExpectedStateChange, SubAgentTaskPacket
from .invariants import apply_state_delta
from .observation import EvidenceReference, Observation, ObservationSource
from .plan import AgentPlan, PlanStep, PlanStepStatus, RetryPolicy
from .reward_facts import RewardFacts
from .state import AgentBudget, AgentTaskState, StateDelta
from .state_abstract import state_abstract_key
from .transition import AgentTransitionEvent, ModelTurnEvent, ModelTurnPurpose, TokenRole, TokenRoleSpan

__all__ = [
    "DOMAIN_SCHEMA_VERSION",
    "DomainModel",
    "AgentActionType",
    "AgentBudget",
    "AgentDecision",
    "AgentOutput",
    "AgentPlan",
    "AgentTaskState",
    "AgentTransitionEvent",
    "ModelTurnEvent",
    "ModelTurnPurpose",
    "ArtifactKind",
    "ArtifactRef",
    "EvidenceReference",
    "ExpectedStateChange",
    "Observation",
    "ObservationSource",
    "PlanStep",
    "PlanStepStatus",
    "RetryPolicy",
    "RewardFacts",
    "StateDelta",
    "SubAgentTaskPacket",
    "TokenRole",
    "TokenRoleSpan",
    "apply_state_delta",
    "state_abstract_key",
]
