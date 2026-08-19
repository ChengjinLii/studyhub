from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import urlparse

from studyhub_rag.config import EXPERIMENT_ROOT, REPO_ROOT

FORBIDDEN_IMPORT_PREFIXES = (
    "app",
    "backend",
    "alembic",
    "asyncpg",
    "mysql",
    "psycopg",
    "pymysql",
    "sqlalchemy",
    "sqlite3",
)
FORBIDDEN_SOURCE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
FORBIDDEN_URI_SCHEMES = {"mysql", "mysql+pymysql", "postgres", "postgresql", "sqlite"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def require_static_snapshot(path: str | Path, snapshot_root: str | Path) -> Path:
    raw = str(path)
    parsed = urlparse(raw)
    if parsed.scheme in FORBIDDEN_URI_SCHEMES or "://" in raw:
        raise ValueError(f"Only local snapshot paths are allowed, got: {raw}")
    resolved = Path(path).resolve()
    root = Path(snapshot_root).resolve()
    if not _inside(resolved, root):
        raise ValueError(f"Input escapes the read-only snapshot root: {resolved}")
    if resolved.suffix.lower() in FORBIDDEN_SOURCE_SUFFIXES:
        raise ValueError(f"Database files are forbidden as RAG inputs: {resolved}")
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def require_experiment_output(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if not _inside(resolved, EXPERIMENT_ROOT):
        raise ValueError(f"Experiment output must remain under {EXPERIMENT_ROOT}: {resolved}")
    if _inside(resolved, REPO_ROOT / "backup"):
        raise ValueError(f"Backup snapshots are immutable: {resolved}")
    return resolved


def verify_source_isolation(source_root: Path | None = None) -> list[str]:
    root = source_root or (EXPERIMENT_ROOT / "src")
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORT_PREFIXES):
                    try:
                        display_path = path.relative_to(EXPERIMENT_ROOT)
                    except ValueError:
                        display_path = path
                    violations.append(f"{display_path} imports forbidden module {module}")
    return violations
