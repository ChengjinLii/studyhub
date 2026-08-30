"""StudyHub's version-locked on-policy distillation compatibility layer."""

from training.opd.token_reward_parity import (
    TokenRewardReference,
    analytic_gradient_at_anchor,
    build_thunlp_token_reward_reference,
    finite_difference_gradient,
    run_synthetic_parity_gate,
    thunlp_on_policy_surrogate_loss,
)

__all__ = [
    "TokenRewardReference",
    "analytic_gradient_at_anchor",
    "build_thunlp_token_reward_reference",
    "finite_difference_gradient",
    "run_synthetic_parity_gate",
    "thunlp_on_policy_surrogate_loss",
]
