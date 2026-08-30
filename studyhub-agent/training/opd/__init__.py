"""StudyHub's version-locked on-policy distillation compatibility layer."""

from training.opd.areal_runtime import (
    aggregate_opd_diagnostics,
    assistant_prediction_mask,
    compute_opd_diagnostics,
    install_areal_opd_bridge,
    install_opd_controller_hooks,
)

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
    "aggregate_opd_diagnostics",
    "analytic_gradient_at_anchor",
    "assistant_prediction_mask",
    "build_thunlp_token_reward_reference",
    "compute_opd_diagnostics",
    "finite_difference_gradient",
    "install_areal_opd_bridge",
    "install_opd_controller_hooks",
    "run_synthetic_parity_gate",
    "thunlp_on_policy_surrogate_loss",
]
