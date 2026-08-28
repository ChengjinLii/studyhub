from __future__ import annotations

from pathlib import Path

from scripts.data.audit_sft_benchmark_alignment import build_audit

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_alignment_audit_uses_only_public_development_and_discloses_bias() -> None:
    audit = build_audit(PROJECT_ROOT)

    assert audit["status"] == "PASS_WITH_ALIGNMENT_BIAS_DISCLOSED"
    assert audit["scope"]["benchmark_split"] == "PUBLIC_DEVELOPMENT_ONLY"
    assert audit["scope"]["sealed_accessed"] is False
    assert sum(audit["development_capability_counts"].values()) == 51
    assert audit["findings"]["rag_training_share"] == 0.740691
    assert audit["findings"]["rag_development_share"] == 0.568627
    assert audit["findings"]["uncovered_development_lanes"] == [
        "long_horizon",
        "memory",
        "recovery_acl",
        "web_research",
    ]
