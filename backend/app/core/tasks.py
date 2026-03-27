from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import inspect

from fastapi import BackgroundTasks


Callback = Callable[..., object]


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

    def schedule(self, callback: Callback, *args, **kwargs) -> None:
        if self.background_tasks is None:
            result = callback(*args, **kwargs)
            if inspect.isawaitable(result):
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(result)
            return
        self.background_tasks.add_task(callback, *args, **kwargs)
