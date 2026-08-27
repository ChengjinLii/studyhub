from __future__ import annotations

from typing import Any


class HermesRegistryOverlay:
    """Temporarily replace Hermes tools and restore exact prior entries.

    One overlay may be active per process. AReaL uses subprocess agent mode, so
    concurrent rollout members receive separate Hermes registries.
    """

    def __init__(self, registry: Any) -> None:
        self.registry = registry
        self._registrations: list[tuple[str, Any, Any]] = []

    @property
    def names(self) -> list[str]:
        return [name for name, _current, _previous in self._registrations]

    def install(
        self,
        *,
        name: str,
        toolset: str,
        schema: dict[str, Any],
        handler: Any,
        max_result_size_chars: int = 12_000,
    ) -> None:
        previous = self.registry.snapshot_registration(name)
        self.registry.register(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            is_async=True,
            description=str(schema["description"]),
            max_result_size_chars=max_result_size_chars,
            override=True,
        )
        current = self.registry.snapshot_registration(name)
        if current is None or current.toolset != toolset or current.handler is not handler:
            if current is not None and current is not previous:
                self.registry.restore_registration(name, current, previous)
            raise RuntimeError(f"Hermes rejected isolated tool override: {name}")
        if self.registry.get_entry(name) is not current:
            self.registry.restore_registration(name, current, previous)
            raise RuntimeError(f"isolated tool is not the active registry entry: {name}")
        self._registrations.append((name, current, previous))

    def restore(self) -> None:
        registrations = list(reversed(self._registrations))
        self._registrations.clear()
        failed = [
            name
            for name, current, previous in registrations
            if not self.registry.restore_registration(name, current, previous)
        ]
        if failed:
            raise RuntimeError(f"failed to restore Hermes tool registrations: {sorted(failed)}")
