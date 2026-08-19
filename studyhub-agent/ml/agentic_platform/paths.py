"""Filesystem boundaries for the standalone StudyHub Agent project."""

from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = AGENT_ROOT.parent
BACKEND_ROOT = WORKSPACE_ROOT / "backend"
SHARED_BACKUP_ROOT = WORKSPACE_ROOT / "backup"
SHARED_MODELS_ROOT = WORKSPACE_ROOT / "models"
AGENT_TRAINING_ARTIFACTS_ROOT = AGENT_ROOT / "training_artifacts"
LEGACY_TRAINING_ARTIFACTS_ROOT = WORKSPACE_ROOT / "training_artifacts"
AGENT_EVALUATION_ARTIFACTS_ROOT = AGENT_ROOT / "evaluation_artifacts"
LEGACY_EVALUATION_ARTIFACTS_ROOT = WORKSPACE_ROOT / "evaluation_artifacts"


def resolve_training_input(
    relative_path: str | Path,
    *,
    project_root: Path = AGENT_ROOT,
) -> Path:
    """Prefer an Agent-local artifact, then read the legacy store without moving it."""
    relative = Path(relative_path)
    local = project_root / "training_artifacts" / relative
    legacy = LEGACY_TRAINING_ARTIFACTS_ROOT / relative
    may_use_legacy = project_root.resolve() == AGENT_ROOT.resolve()
    return local if local.exists() or not may_use_legacy or not legacy.exists() else legacy


def resolve_evaluation_input(relative_path: str | Path) -> Path:
    """Prefer an Agent-local evaluation artifact, then use the legacy read-only copy."""
    relative = Path(relative_path)
    local = AGENT_EVALUATION_ARTIFACTS_ROOT / relative
    legacy = LEGACY_EVALUATION_ARTIFACTS_ROOT / relative
    return local if local.exists() or not legacy.exists() else legacy
