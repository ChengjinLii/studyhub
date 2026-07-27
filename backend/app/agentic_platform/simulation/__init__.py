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
from .clock import ClockState, SnapshotClock
from .random_source import DeterministicRandomSource
from .snapshot_research_environment import SnapshotResearchEnvironment
from .snapshot_skill_executor import SnapshotEnvironmentActionExecutor, SnapshotSkillExecutor
from .trajectory import ModelIORecord, TrajectoryManifest, TransitionJsonlSink
from .world_snapshot import (
    CatalogSplit,
    InMemoryWorldSnapshotArtifactStore,
    ResolvedStudyHubWorld,
    SnapshotCatalog,
    SnapshotDataLeakageError,
    SnapshotMaterial,
    SnapshotPdfPage,
    SnapshotPdfPageIndex,
    SnapshotPermissionRecord,
    SnapshotPermissionState,
    SnapshotRetrieverEntry,
    SnapshotRetrieverIndex,
    StudyHubWorldSnapshot,
    StudyHubWorldSnapshotBuilder,
)

__all__ = [
    "AgentEnvironment",
    "EnvironmentActionExecutor",
    "EnvironmentActionResult",
    "EnvironmentKind",
    "EnvironmentReset",
    "EnvironmentSnapshot",
    "EnvironmentStep",
    "ClockState",
    "SnapshotClock",
    "DeterministicRandomSource",
    "LiveStudyHubEnvironment",
    "ReplayRequest",
    "ReplayResult",
    "ScenarioAction",
    "ScenarioSpec",
    "SimulatedStudyHubEnvironment",
    "SnapshotReplayRunner",
    "SnapshotResearchEnvironment",
    "SnapshotSkillExecutor",
    "SnapshotEnvironmentActionExecutor",
    "SnapshotStudyHubEnvironment",
    "CatalogSplit",
    "InMemoryWorldSnapshotArtifactStore",
    "ResolvedStudyHubWorld",
    "SnapshotCatalog",
    "SnapshotDataLeakageError",
    "SnapshotMaterial",
    "SnapshotPdfPage",
    "SnapshotPdfPageIndex",
    "SnapshotPermissionRecord",
    "SnapshotPermissionState",
    "SnapshotRetrieverEntry",
    "SnapshotRetrieverIndex",
    "StudyHubWorldSnapshot",
    "StudyHubWorldSnapshotBuilder",
    "ModelIORecord",
    "TransitionJsonlSink",
    "TrajectoryManifest",
]
