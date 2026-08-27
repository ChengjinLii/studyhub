from pathlib import Path

from scripts.train.capture_run_metadata import cached_sha256, load_hash_cache, save_hash_cache


def test_model_hash_cache_reuses_only_an_identical_file_identity(tmp_path: Path) -> None:
    model_file = tmp_path / "model.safetensors"
    model_file.write_bytes(b"first")
    cache_path = tmp_path / "hash-cache.json"
    cache = load_hash_cache(cache_path)

    first_digest, first_source = cached_sha256(model_file, cache)
    save_hash_cache(cache_path, cache)
    second_cache = load_hash_cache(cache_path)
    second_digest, second_source = cached_sha256(model_file, second_cache)

    assert first_source == "computed"
    assert second_source == "verified_stat_cache"
    assert second_digest == first_digest

    model_file.write_bytes(b"second")
    changed_digest, changed_source = cached_sha256(model_file, second_cache)

    assert changed_source == "computed"
    assert changed_digest != first_digest
