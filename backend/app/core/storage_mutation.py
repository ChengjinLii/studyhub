from __future__ import annotations

from collections.abc import Callable, Iterable
import logging


logger = logging.getLogger(__name__)


class StorageMutation:
    """Tracks object-store changes until the database commit is known."""

    def __init__(self, delete_key: Callable[[str | None], None]) -> None:
        self._delete_key = delete_key
        self._new_keys: list[str] = []
        self._replaced_keys: list[str] = []

    def record_new(self, key: str | None) -> None:
        self._append_unique(self._new_keys, key)

    def replace_after_commit(self, key: str | None) -> None:
        self._append_unique(self._replaced_keys, key)

    def rollback(self) -> None:
        self._delete_many(reversed(self._new_keys), event="storage_mutation_rollback")
        self._clear()

    def finalize(self) -> None:
        new_keys = set(self._new_keys)
        self._delete_many(
            (key for key in self._replaced_keys if key not in new_keys),
            event="storage_mutation_finalize",
        )
        self._clear()

    @staticmethod
    def _append_unique(target: list[str], key: str | None) -> None:
        normalized = str(key or "").strip()
        if normalized and normalized not in target:
            target.append(normalized)

    def _delete_many(self, keys: Iterable[str], *, event: str) -> None:
        for key in keys:
            try:
                self._delete_key(key)
            except Exception:  # noqa: BLE001
                logger.exception("Deferred storage cleanup failed", extra={"event": event})

    def _clear(self) -> None:
        self._new_keys.clear()
        self._replaced_keys.clear()
