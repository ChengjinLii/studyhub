"""Replaceable environments, deterministic replay, and trace export helpers.

Nothing in this package chooses an Agent's business intent or next action.
Policies remain free to use the registered capability catalog; scenarios are
only explicit fixtures/snapshots used to make a selected action sequence
replayable.
"""

from .environment import (
    AgentEnvironment,
    EnvironmentActionExecutor,
    EnvironmentActionResult,
    EnvironmentReset,
    EnvironmentStep,
    LiveStudyHubEnvironment,
    SimulatedStudyHubEnvironment,
    SnapshotStudyHubEnvironment,
)
from .replay import ReplayRequest, ReplayResult, SnapshotReplayRunner
from .scenario import ScenarioAction, ScenarioSpec
from .snapshot import EnvironmentKind, EnvironmentSnapshot
from .trajectory import ModelIORecord, TrajectoryManifest, TransitionJsonlSink

__all__ = [
    "AgentEnvironment",
    "EnvironmentActionExecutor",
    "EnvironmentActionResult",
    "EnvironmentKind",
    "EnvironmentReset",
    "EnvironmentSnapshot",
    "EnvironmentStep",
    "LiveStudyHubEnvironment",
    "ReplayRequest",
    "ReplayResult",
    "ScenarioAction",
    "ScenarioSpec",
    "SimulatedStudyHubEnvironment",
    "SnapshotReplayRunner",
    "SnapshotStudyHubEnvironment",
    "ModelIORecord",
    "TransitionJsonlSink",
    "TrajectoryManifest",
]
