from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.train import guarded_gpu_launch as guard
from scripts.train.guarded_gpu_launch import interrupt_group, process_group_exists, terminate_group


def test_guard_cleans_orphaned_children_after_launcher_exits() -> None:
    launcher = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import subprocess, sys; "
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "sys.exit(1)"
            ),
        ],
        start_new_session=True,
    )
    assert launcher.wait(timeout=5) == 1
    assert process_group_exists(launcher.pid)

    terminate_group(launcher)

    assert not process_group_exists(launcher.pid)


def test_guard_interrupts_owned_process_group_gracefully() -> None:
    launcher = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )

    interrupt_group(launcher, grace_seconds=2)

    assert launcher.wait(timeout=2) != 0
    assert not process_group_exists(launcher.pid)


def shared_sample(**changes):
    sample = {
        "gpu": "0",
        "used_mib": 55000,
        "free_mib": 25000,
        "ownership": {"own_mib": 45000, "foreign_mib": 10000, "foreign_pids": [123]},
        "allow_shared": True,
        "max_used_mib": 68000,
        "max_own_used_mib": 52000,
        "min_runtime_free_mib": 12000,
    }
    return {**sample, **changes}


def test_shared_guard_allows_foreign_process_with_headroom() -> None:
    guard.validate_resource_sample(**shared_sample())


def test_exclusive_guard_still_rejects_foreign_process() -> None:
    with pytest.raises(RuntimeError, match="unrelated compute processes"):
        guard.validate_resource_sample(**shared_sample(allow_shared=False))


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"used_mib": 68001}, "total guard"),
        ({"free_mib": 11999}, "below shared reserve"),
        ({"ownership": {"own_mib": 52001, "foreign_pids": []}}, "own memory"),
    ],
)
def test_shared_guard_still_enforces_memory_budgets(changes, reason) -> None:
    with pytest.raises(RuntimeError, match=reason):
        guard.validate_resource_sample(**shared_sample(**changes))


def test_memory_accounting_separates_entire_training_group(monkeypatch) -> None:
    monkeypatch.setattr(
        guard.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="10, 30000\n11, 15000\n12, 500\n")
    )
    monkeypatch.setattr(guard, "process_group", lambda pid: 99 if pid in (10, 11) else 100)
    assert guard.memory_ownership("0", 99) == {"own_mib": 45000, "foreign_mib": 500, "foreign_pids": [12]}


def test_shared_guard_rejects_unavailable_process_memory(monkeypatch) -> None:
    monkeypatch.setattr(guard.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="10, [N/A]\n"))
    with pytest.raises(RuntimeError, match="accounting unavailable"):
        guard.memory_ownership("0", 99)
