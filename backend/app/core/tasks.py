from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import BackgroundTasks


Callback = Callable[[], None]


@dataclass
class AfterCommitQueue:
    """先把 after-commit 入口留出来，后续事务适配时直接接入。"""

    callbacks: list[Callback] = field(default_factory=list)

    def add(self, callback: Callback) -> None:
        self.callbacks.append(callback)

    def run(self) -> None:
        while self.callbacks:
            callback = self.callbacks.pop(0)
            callback()

    def clear(self) -> None:
        self.callbacks.clear()


@dataclass
class BackgroundDispatcher:
    background_tasks: BackgroundTasks | None = None

    def schedule(self, callback: Callback) -> None:
        if self.background_tasks is None:
            callback()
            return
        self.background_tasks.add_task(callback)
