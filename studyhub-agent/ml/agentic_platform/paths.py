"""Filesystem boundaries for the standalone StudyHub Agent project."""

from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = AGENT_ROOT.parent
BACKEND_ROOT = WORKSPACE_ROOT / "backend"
SHARED_BACKUP_ROOT = WORKSPACE_ROOT / "backup"
SHARED_MODELS_ROOT = WORKSPACE_ROOT / "models"
AGENT_TRAINING_ARTIFACTS_ROOT = AGENT_ROOT / "training_artifacts"
AGENT_EVALUATION_ARTIFACTS_ROOT = AGENT_ROOT / "evaluation_artifacts"


def resolve_training_input(
    relative_path: str | Path,
    *,
    project_root: Path = AGENT_ROOT,
) -> Path:
    """Resolve a training artifact inside the standalone Agent project."""
    return project_root / "training_artifacts" / Path(relative_path)


def resolve_evaluation_input(relative_path: str | Path) -> Path:
    """Resolve an evaluation artifact inside the standalone Agent project."""
    return AGENT_EVALUATION_ARTIFACTS_ROOT / Path(relative_path)
