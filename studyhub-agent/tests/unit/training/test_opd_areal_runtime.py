import os
from pathlib import Path

import pytest
import torch
import torch.nn.functional as F

from training.opd.areal_runtime import (
    _chunked_selected_log_probs,
    _chunked_top_k_log_probs,
    aggregate_opd_diagnostics,
    assistant_prediction_mask,
    compute_opd_diagnostics,
    install_areal_opd_bridge,
    prediction_turn_ids,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_opd_launcher_separates_code_and_artifact_roots() -> None:
    launcher = (PROJECT_ROOT / "scripts/train/run_qwen35_4b_opd.sh").read_text()
    config = (PROJECT_ROOT / "configs/train/qwen35-4b-strict-opd.yaml").read_text()

    assert 'ARTIFACT_ROOT="${STUDYHUB_OPD_ARTIFACT_ROOT:-${PROJECT_ROOT}}"' in launcher
    assert 'VENV_DIR="${STUDYHUB_TRAIN_VENV:-${ARTIFACT_ROOT}/.venv-train}"' in launcher
    assert 'DATA_MANIFEST="${ARTIFACT_ROOT}/datasets/processed/' in launcher
    assert 'CHECKPOINT_ROOT="${ARTIFACT_ROOT}/artifacts/areal/checkpoints/' in launcher
    assert '${PROJECT_ROOT}/artifacts/areal' not in launcher
    assert "libcudart.so.12" in launcher
    assert "STUDYHUB_CUDA_RUNTIME_LIBRARY_PATH" in launcher
    assert config.count(
        "LD_LIBRARY_PATH: ${oc.env:STUDYHUB_CUDA_RUNTIME_LIBRARY_PATH}"
    ) >= 5

    probe = (PROJECT_ROOT / "scripts/train/run_opd_policy_probe.py").read_text()
    assert 'parser.add_argument("--artifact-root"' in probe
    assert 'artifact_root / ".vendor/hermes-agent"' in probe
    assert 'model_overlay = artifact_root /' in probe


def test_prediction_mask_does_not_cross_trajectory_boundaries() -> None:
    mask = torch.tensor([[0, 0, 1, 1], [0, 1, 0, 1]], dtype=torch.float32)

    shifted = assistant_prediction_mask(mask)

    assert torch.equal(
        shifted,
        torch.tensor([[0, 1, 1, 0], [1, 0, 1, 0]], dtype=torch.float32),
    )


def test_prediction_turn_ids_follow_next_token_alignment() -> None:
    turn_ids = torch.tensor([[-1, 0, 0, 1, 1]])

    assert torch.equal(prediction_turn_ids(turn_ids), torch.tensor([[0, 0, 1, 1, -1]]))


def test_chunked_sparse_scores_match_full_log_softmax() -> None:
    logits = torch.tensor(
        [[2.0, 1.0, 0.0, -1.0], [0.0, 2.0, 1.0, -1.0], [1.0, 0.0, 2.0, -1.0]],
        dtype=torch.float64,
    )
    token_ids = torch.tensor([[0, 2], [1, 0], [2, 1]])
    expected = F.log_softmax(logits / 0.7, dim=-1).gather(-1, token_ids)

    actual = _chunked_selected_log_probs(
        logits, token_ids, temperature=0.7, chunk_size=1
    )
    top_ids, top_log_probs = _chunked_top_k_log_probs(
        logits,
        top_k=2,
        temperature=0.7,
        chunk_size=1,
    )

    assert torch.allclose(actual, expected.float(), atol=1e-6, rtol=0)
    expected_top = F.log_softmax(logits / 0.7, dim=-1).gather(-1, top_ids)
    assert torch.allclose(top_log_probs, expected_top.float(), atol=1e-6, rtol=0)


def test_opd_diagnostics_report_overlap_mass_and_advantage() -> None:
    student_ids = torch.tensor([[0, 1], [1, 2]])
    teacher_ids = torch.tensor([[1, 2], [1, 0]])
    student_log_probs = torch.log(torch.tensor([[0.6, 0.3], [0.5, 0.2]]))
    teacher_on_student = torch.log(torch.tensor([[0.4, 0.5], [0.6, 0.1]]))
    teacher_log_probs = torch.log(torch.tensor([[0.7, 0.2], [0.6, 0.25]]))
    mask = torch.tensor([1.0, 0.0])
    turn_ids = torch.tensor([0, -1])

    result = compute_opd_diagnostics(
        student_ids,
        student_log_probs,
        teacher_on_student,
        teacher_ids,
        teacher_log_probs,
        mask,
        turn_ids,
    )

    assert result["opd_scored_tokens"].item() == 1
    assert result["opd_overlap_ratio"].item() == pytest.approx(0.5)
    assert result["opd_student_top_k_mass"].item() == pytest.approx(0.9)
    assert result["opd_teacher_on_student_mass"].item() == pytest.approx(0.9)
    assert result["opd_teacher_logprob_advantage"].item() > 0
    assert result["opd_teacher_student_kl"].item() >= 0
    assert result["opd_student_top_k_entropy"].item() > 0
    assert result["opd_teacher_on_student_entropy"].item() > 0
    assert result["opd_turn_0_scored_tokens"].item() == 1
    assert result["opd_turn_1_scored_tokens"].item() == 0


def test_opd_diagnostic_aggregation_is_token_weighted() -> None:
    def row(mask: torch.Tensor, turn_ids: torch.Tensor) -> dict[str, torch.Tensor]:
        ids = torch.tensor([[0, 1], [1, 2]])
        student = torch.log(torch.tensor([[0.6, 0.3], [0.5, 0.2]]))
        teacher = torch.log(torch.tensor([[0.4, 0.5], [0.6, 0.1]]))
        teacher_ids = torch.tensor([[1, 2], [1, 0]])
        teacher_top = torch.log(torch.tensor([[0.7, 0.2], [0.6, 0.25]]))
        return compute_opd_diagnostics(
            ids,
            student,
            teacher,
            teacher_ids,
            teacher_top,
            mask,
            turn_ids,
        )

    first = row(torch.tensor([1.0, 0.0]), torch.tensor([0, -1]))
    second = row(torch.tensor([1.0, 1.0]), torch.tensor([0, 1]))
    merged = aggregate_opd_diagnostics([first, second])

    assert merged["opd_scored_tokens"] == 3
    assert merged["opd_reward_wings"] == 6
    assert merged["opd_turn_0_scored_tokens"] == 2
    assert merged["opd_turn_1_scored_tokens"] == 1
    assert merged["opd_active_turns"] == 2
    assert merged["opd_teacher_student_kl"] >= 0
    assert merged["opd_student_top_k_entropy"] > 0
    assert merged["opd_teacher_on_student_entropy"] > 0


def test_opd_diagnostics_reject_empty_assistant_mask() -> None:
    values = torch.zeros((2, 2))
    with pytest.raises(RuntimeError, match="no trainable assistant tokens"):
        compute_opd_diagnostics(
            torch.zeros((2, 2), dtype=torch.long),
            values,
            values,
            torch.zeros((2, 2), dtype=torch.long),
            values,
            torch.zeros(2),
        )


def test_opd_config_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("areal")
    from areal.api.cli_args import load_expr_config

    from training.opd.config import StudyHubOPDConfig

    monkeypatch.setenv("STUDYHUB_AREAL_ADMIN_API_KEY", "unit-test-only")
    monkeypatch.setenv(
        "STUDYHUB_CUDA_RUNTIME_LIBRARY_PATH", "/unit-test/cuda-runtime/lib"
    )
    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    config, _ = load_expr_config(
        ["--config", str(PROJECT_ROOT / "configs/train/qwen35-4b-strict-opd.yaml")],
        StudyHubOPDConfig,
    )

    assert config.opd_top_k == 16
    assert config.opd_top_k_strategy == "only_stu"
    assert config.actor.kl_ctl == 0
    assert config.ref is None
    assert config.teacher.engine_type == "train"


def test_areal_bridge_install_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("areal")
    monkeypatch.delenv("STUDYHUB_OPD_STUDENT_ADAPTER", raising=False)

    install_areal_opd_bridge()
    install_areal_opd_bridge()

    from areal.engine.fsdp_engine import FSDPPPOActor

    assert callable(FSDPPPOActor.opd_compute_anchor)
    assert callable(FSDPPPOActor.opd_score_selected)
    assert callable(FSDPPPOActor.opd_update)
    assert os.environ.get("STUDYHUB_OPD_STUDENT_ADAPTER") is None
