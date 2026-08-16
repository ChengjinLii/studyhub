from __future__ import annotations

from app.core import config
from app.core.config import Settings


def test_release_build_marker_is_used_without_git_checkout(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "STACK_ROOT", tmp_path)
    (tmp_path / ".build-git-sha").write_text("abc1234def56\n", encoding="ascii")

    assert Settings().resolved_build_git_sha == "abc1234def56"


def test_release_build_marker_rejects_untrusted_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "STACK_ROOT", tmp_path)
    (tmp_path / ".build-git-sha").write_text("not a git sha\n", encoding="ascii")
    monkeypatch.setattr(config.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))

    assert Settings().resolved_build_git_sha == "local-dev"
