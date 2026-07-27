"""Manifest-driven, provider-agnostic Agent pilot orchestration."""

from .pilot import (
    PilotConfigurationError,
    PilotRunReport,
    PilotScenario,
    PilotScenarioManifest,
    PilotScenarioOutcome,
    run_pilot,
)
from .validation import (
    PilotGateAuthorizationError,
    PilotGateReport,
    authorize_training_collection,
    validate_pilot_dataset,
)

__all__ = [
    "PilotConfigurationError",
    "PilotGateReport",
    "PilotGateAuthorizationError",
    "PilotRunReport",
    "PilotScenario",
    "PilotScenarioManifest",
    "PilotScenarioOutcome",
    "run_pilot",
    "authorize_training_collection",
    "validate_pilot_dataset",
]
