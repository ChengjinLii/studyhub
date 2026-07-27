"""Stable domain contracts shared by every agent runtime implementation.

The package intentionally contains no FastAPI, ORM, LangGraph, or model-provider
imports.  That keeps persisted runs and future training data independent of the
runtime that produced them.
"""

from ._base import DOMAIN_SCHEMA_VERSION, DomainModel
from .artifact import ArtifactKind, ArtifactRef
from .data_policy import (
    DataSensitivity,
    ExportTarget,
    LicenseClass,
    SourceScope,
    TrainingDataExportError,
    TrainingDataPolicy,
    aggregate_data_policies,
    manifest_policy_fields,
    require_export_allowed,
)
from .decision import AgentActionType, AgentDecision, AgentOutput, ExpectedStateChange, SubAgentTaskPacket
from .invariants import apply_state_delta
from .observation import EvidenceReference, Observation, ObservationSource
from .plan import AgentPlan, PlanStep, PlanStepStatus, RetryPolicy
from .reward_facts import RewardFacts
from .state import AgentBudget, AgentTaskState, StateDelta
from .state_abstract import StateGroupFeatures, state_abstract_key, state_group_features, state_group_key_v2
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
    "DataSensitivity",
    "EvidenceReference",
    "ExpectedStateChange",
    "ExportTarget",
    "LicenseClass",
    "Observation",
    "ObservationSource",
    "PlanStep",
    "PlanStepStatus",
    "RetryPolicy",
    "RewardFacts",
    "SourceScope",
    "StateGroupFeatures",
    "StateDelta",
    "SubAgentTaskPacket",
    "TokenRole",
    "TokenRoleSpan",
    "TrainingDataExportError",
    "TrainingDataPolicy",
    "aggregate_data_policies",
    "manifest_policy_fields",
    "apply_state_delta",
    "state_abstract_key",
    "state_group_features",
    "state_group_key_v2",
    "require_export_allowed",
]
