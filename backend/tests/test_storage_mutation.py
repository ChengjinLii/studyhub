from __future__ import annotations

from app.core.storage_mutation import StorageMutation


def test_storage_mutation_rollback_deletes_only_new_keys_in_reverse_order() -> None:
    deleted: list[str] = []
    mutation = StorageMutation(deleted.append)
    mutation.replace_after_commit("old-file")
    mutation.record_new("new-file")
    mutation.record_new("new-preview")

    mutation.rollback()

    assert deleted == ["new-preview", "new-file"]


def test_storage_mutation_finalize_deletes_replaced_keys_once() -> None:
    deleted: list[str] = []
    mutation = StorageMutation(deleted.append)
    mutation.record_new("new-file")
    mutation.replace_after_commit("old-file")
    mutation.replace_after_commit("old-file")
    mutation.replace_after_commit("new-file")

    mutation.finalize()

    assert deleted == ["old-file"]


def test_storage_mutation_cleanup_failure_does_not_mask_committed_work() -> None:
    deleted: list[str] = []

    def delete_key(key: str | None) -> None:
        if key == "unavailable":
            raise RuntimeError("storage unavailable")
        if key:
            deleted.append(key)

    mutation = StorageMutation(delete_key)
    mutation.replace_after_commit("unavailable")
    mutation.replace_after_commit("old-file")

    mutation.finalize()

    assert deleted == ["old-file"]
