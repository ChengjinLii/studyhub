import json
import math
from pathlib import Path

import pytest

from training.opd.token_reward_parity import (
    analytic_gradient_at_anchor,
    build_thunlp_token_reward_reference,
    finite_difference_gradient,
    run_synthetic_parity_gate,
    thunlp_on_policy_surrogate_loss,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_only_student_topk_reward_uses_conditional_student_weights() -> None:
    student = (((2.0, 1.0, 0.0),),)
    teacher = (((1.0, 2.0, 0.0),),)
    reference = build_thunlp_token_reward_reference(student, teacher, ((1,),), top_k=2)

    weight_first = 1.0 / (1.0 + math.exp(-1.0))
    weight_second = 1.0 - weight_first
    assert reference.top_k_ids == (((0, 1),),)
    assert reference.student_conditional_weights[0][0] == (
        weight_first,
        weight_second,
    )
    assert reference.raw_token_rewards[0][0] == (
        -weight_first,
        weight_second,
    )
    assert math.isclose(reference.token_mean_loss, math.tanh(0.5), rel_tol=0, abs_tol=1e-12)


def test_response_mask_is_applied_before_k_sum_and_token_mean() -> None:
    student = (((2.0, 1.0, 0.0), (0.0, 2.0, 1.0)),)
    teacher = (((1.0, 2.0, 0.0), (0.0, 1.0, 2.0)),)
    reference = build_thunlp_token_reward_reference(student, teacher, ((1, 0),), top_k=2)

    assert reference.advantages[0][1] == (0.0, 0.0)
    assert reference.token_losses[0][1] == 0.0
    assert math.isclose(
        thunlp_on_policy_surrogate_loss(student, reference),
        reference.token_mean_loss,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_analytic_gradient_matches_finite_difference_at_on_policy_anchor() -> None:
    result = run_synthetic_parity_gate()

    assert result["status"] == "PASS_THUNLP_TOKEN_REWARD_DIRECT_MATH"
    assert result["checks"]["finite_difference_gradient_matches"] is True
    assert result["checks"]["gradient_descent_direction_decreases_surrogate"] is True
    assert result["metrics"]["gradient_max_abs_error"] <= 2e-7


def test_explicit_gradient_helpers_match_on_small_fixture() -> None:
    student = (((2.0, 1.0, 0.0),),)
    teacher = (((1.0, 2.0, 0.0),),)
    reference = build_thunlp_token_reward_reference(student, teacher, ((1,),), top_k=2)
    analytic = analytic_gradient_at_anchor(reference)
    numerical = finite_difference_gradient(student, reference)

    for analytic_value, numerical_value in zip(analytic[0][0], numerical[0][0], strict=True):
        assert math.isclose(analytic_value, numerical_value, rel_tol=0, abs_tol=2e-7)


def test_upstream_lock_prevents_native_verl_losses_being_mislabeled() -> None:
    lock = json.loads((PROJECT_ROOT / "training/opd/upstream.lock.json").read_text(encoding="utf-8"))

    assert lock["thunlp_opd"]["commit"] == "ac26e38d6f1572eb027597b48a9f4e01f6915ef8"
    assert lock["official_verl"]["commit"] == "ea53291385ce764019a2b40733605f21d8317583"
    assert lock["primary_recipe"] == {
        "name": "THUNLP token_reward_direct",
        "adv_estimator": "token_reward_direct",
        "log_prob_top_k": 16,
        "top_k_strategy": "only_stu",
        "reward_weight_mode": "student_p",
        "loss_aggregation": "sum-k-then-token-mean",
        "standard_reference_kl": False,
    }
    assert lock["compatibility"]["official_sampled_token_k1_equivalent"] is False
    assert lock["compatibility"]["official_teacher_top_k_forward_kl_equivalent"] is False
    assert lock["compatibility"]["runtime_backend_parity"] == "NOT_RUN"


def test_torch_candidate_matches_independent_oracle() -> None:
    pytest.importorskip("torch")
    from training.opd.verl_compat import run_torch_candidate_parity_gate

    result = run_torch_candidate_parity_gate()

    assert result["status"] == "PASS_TORCH_COMPATIBILITY_KERNEL"
    assert all(result["checks"].values())
    assert result["metrics"]["gradient_max_abs_error"] <= 2e-12
