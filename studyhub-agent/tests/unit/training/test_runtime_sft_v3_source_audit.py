from scripts.data.audit_runtime_sft_v3_by_source import percentile


def test_source_audit_percentile_is_nearest_rank() -> None:
    assert percentile([], 0.5) == 0
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([1, 2, 3, 4], 0.9) == 4
