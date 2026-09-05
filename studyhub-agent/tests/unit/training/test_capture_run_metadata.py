import json
from pathlib import Path
from types import SimpleNamespace

from scripts.train.capture_run_metadata import cached_sha256, finish, load_hash_cache, save_hash_cache


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


def test_shared_gpu_summary_separates_owned_and_external_memory(tmp_path: Path) -> None:
    output = tmp_path / "run.json"
    output.write_text("{}")
    telemetry = tmp_path / "gpu.csv"
    telemetry.write_text(
        "memory_used_mib,utilization_gpu_pct,own_memory_used_mib,foreign_memory_used_mib,foreign_process_count\n"
        "46000,30,45000,1000,1\n48000,40,45500,2500,2\n"
    )
    finish(SimpleNamespace(output=output, gpu_csv=telemetry, status=0))
    summary = json.loads(output.read_text())["resource_summary"]
    assert summary["peak_memory_used_mib"] == 48000
    assert summary["peak_own_memory_used_mib"] == 45500
    assert summary["peak_foreign_memory_used_mib"] == 2500
    assert summary["peak_foreign_process_count"] == 2
