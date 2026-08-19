"""Fail-closed environment checks for the StudyHub offline Agent pilot."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


class OfflinePilotIsolationError(RuntimeError):
    """The requested pilot could reach a production or remote dependency."""


_PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})
_DATABASE_VARIABLES = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
)
_REMOTE_MODEL_VARIABLES = (
    "ANTHROPIC_BASE_URL",
    "OPENAI_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)
_LOCAL_PROVIDER_PREFIXES = ("fixture-snapshot", "local-qwen")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_artifact_root() -> Path:
    return repository_root() / "artifacts" / "agentic_platform" / "offline-pilot"


def assert_offline_pilot_environment(
    *,
    provider: str,
    trajectory_root: str | Path,
    output_dir: str | Path,
    model_path: str | Path | None = None,
    adapter_path: str | Path | None = None,
    artifact_root: str | Path | None = None,
) -> None:
    """Reject production configuration, remote providers, and escaped paths.

    Snapshot Skills already disable web and scholar access.  This guard adds a
    process-level contract so the pilot cannot silently inherit a production
    database URL or write outside its ignored artifact tree.
    """

    normalized_provider = provider.strip().lower()
    if not normalized_provider.startswith(_LOCAL_PROVIDER_PREFIXES):
        raise OfflinePilotIsolationError("offline_provider_must_be_local_or_fixture")

    environment = os.getenv("STUDYHUB_ENVIRONMENT", "").strip().lower()
    if environment in _PRODUCTION_ENVIRONMENTS:
        raise OfflinePilotIsolationError("production_environment_is_forbidden")

    inherited_database = _first_nonblank_environment(_DATABASE_VARIABLES)
    if inherited_database is not None:
        raise OfflinePilotIsolationError(f"database_configuration_is_forbidden:{inherited_database}")

    inherited_remote_model = _first_remote_model_environment(_REMOTE_MODEL_VARIABLES)
    if inherited_remote_model is not None:
        raise OfflinePilotIsolationError(f"remote_model_configuration_is_forbidden:{inherited_remote_model}")

    root = _resolved_path(artifact_root or default_artifact_root())
    _assert_path_within(trajectory_root, root=root, label="trajectory_root")
    _assert_path_within(output_dir, root=root, label="output_dir")

    production_env = repository_root() / "private" / ".env.production"
    if production_env.exists() or production_env.is_symlink():
        raise OfflinePilotIsolationError("production_env_file_present_in_offline_worktree")

    for label, value in (("model_path", model_path), ("adapter_path", adapter_path)):
        if value is None:
            continue
        path = _resolved_path(value)
        if not path.exists() or not path.is_dir():
            raise OfflinePilotIsolationError(f"{label}_must_be_an_existing_local_directory")


def _assert_path_within(value: str | Path, *, root: Path, label: str) -> None:
    path = _resolved_path(value)
    if not path.is_relative_to(root):
        raise OfflinePilotIsolationError(f"{label}_escapes_offline_artifact_root")


def _resolved_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repository_root() / path
    return path.resolve(strict=False)


def _first_nonblank_environment(names: tuple[str, ...]) -> str | None:
    for name in names:
        if os.getenv(name, "").strip():
            return name
    return None


def _first_remote_model_environment(names: tuple[str, ...]) -> str | None:
    for name in names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return name
    return None


__all__ = [
    "OfflinePilotIsolationError",
    "assert_offline_pilot_environment",
    "default_artifact_root",
    "repository_root",
]
