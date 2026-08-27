from __future__ import annotations

import subprocess
import sys

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
