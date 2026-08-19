from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ml.agentic_platform.paths import AGENT_ROOT, BACKEND_ROOT, WORKSPACE_ROOT


def test_workspace_boundaries_are_explicit() -> None:
    assert AGENT_ROOT.name == "studyhub-agent"
    assert WORKSPACE_ROOT == AGENT_ROOT.parent
    assert BACKEND_ROOT == WORKSPACE_ROOT / "backend"
    assert (AGENT_ROOT / "pyproject.toml").is_file()


def test_hermes_patch_matches_lock_and_has_a_small_surface() -> None:
    integration = AGENT_ROOT / "integrations/hermes"
    lock = json.loads((integration / "upstream.lock.json").read_text(encoding="utf-8"))
    patch = integration / lock["patch"]
    digest = hashlib.sha256(patch.read_bytes()).hexdigest()

    assert digest == lock["patch_sha256"]
    touched = {
        line.removeprefix("+++ b/")
        for line in patch.read_text(encoding="utf-8").splitlines()
        if line.startswith("+++ b/")
    }
    assert touched == {
        "hermes_cli/_parser.py",
        "hermes_cli/banner.py",
        "hermes_cli/main.py",
        "hermes_cli/skin_engine.py",
    }


def test_launcher_is_owned_by_the_standalone_project() -> None:
    launcher = (AGENT_ROOT / "bin/studyhub-agent").read_text(encoding="utf-8")

    assert "ai_platform/agents" not in launcher
    assert 'HERMES_SKIN="studyhub"' in launcher
    assert "HERMES_SKINS_DIR" in launcher
    assert "hermes_cli.main" in launcher


def test_standalone_package_does_not_import_the_website() -> None:
    package_root = AGENT_ROOT / "studyhub_agent"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(package_root.rglob("*.py"))
    )

    assert "from app." not in source
    assert "import app." not in source


def test_legacy_agent_paths_are_absent() -> None:
    assert not (WORKSPACE_ROOT / "ml").exists()
    assert not (WORKSPACE_ROOT / "reports/recagent/agentic-platform").exists()
    assert not (WORKSPACE_ROOT / "ai_platform").exists()
    assert not (WORKSPACE_ROOT / "training_artifacts").exists()
    assert not (WORKSPACE_ROOT / "evaluation_artifacts").exists()
    assert (AGENT_ROOT / "ai_platform/rag_experiments").is_dir()
    assert (AGENT_ROOT / "training_artifacts").is_dir()
    assert (AGENT_ROOT / "evaluation_artifacts").is_dir()


def test_bots_are_local_only() -> None:
    root_ignore = (WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "/bots/" in root_ignore
    assert not any(path.parts[0] == "bots" for path in _tracked_workspace_paths())


def _tracked_workspace_paths() -> list[Path]:
    import subprocess

    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=WORKSPACE_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [Path(raw.decode()) for raw in output.split(b"\0") if raw]
