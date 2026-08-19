from __future__ import annotations

import hashlib
import json

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


def test_bots_are_local_only() -> None:
    root_ignore = (WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "/bots/" in root_ignore
    assert (WORKSPACE_ROOT / "bots/qq_studyhub_bot/server.py").is_file()
