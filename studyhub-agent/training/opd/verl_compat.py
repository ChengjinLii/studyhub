"""Torch compatibility kernel for the selected THUNLP OPD recipe.

This is intentionally a small integration target rather than a vendor patch.
The runtime teacher scorer must provide teacher log probabilities on the IDs
selected by the student. Full teacher logits are accepted here only to make the
synthetic parity gate self-contained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F

from training.opd.token_reward_parity import (
    analytic_gradient_at_anchor,
    build_thunlp_token_reward_reference,
)


@dataclass(frozen=True)
class TorchTokenRewardAnchor:
    student_top_k_ids: torch.Tensor
    student_top_k_log_probs: torch.Tensor
    teacher_on_student_log_probs: torch.Tensor
    student_conditional_weights: torch.Tensor
    raw_token_rewards: torch.Tensor
    advantages: torch.Tensor
    response_mask: torch.Tensor
    student_temperature: float


def build_token_reward_from_selected_ids(
    student_top_k_ids: torch.Tensor,
    student_top_k_log_probs: torch.Tensor,
    teacher_on_student_log_probs: torch.Tensor,
    response_mask: torch.Tensor,
    *,
    student_temperature: float,
) -> TorchTokenRewardAnchor:
    """Build detached ``only_stu``/``student_p`` rewards from aligned scores."""

    if student_top_k_ids.shape != student_top_k_log_probs.shape:
        raise ValueError("student IDs and log probabilities must have the same shape")
    if teacher_on_student_log_probs.shape != student_top_k_log_probs.shape:
        raise ValueError("teacher scores must align with the student-selected IDs")
    if response_mask.shape != student_top_k_log_probs.shape[:2]:
        raise ValueError("response_mask must match [batch, sequence]")
    if student_top_k_log_probs.ndim != 3:
        raise ValueError("selected token tensors must have shape [batch, sequence, top_k]")
    if student_temperature <= 0:
        raise ValueError("student_temperature must be positive")
    if not torch.all((response_mask == 0) | (response_mask == 1)):
        raise ValueError("response_mask must be binary")
    if response_mask.sum().item() == 0:
        raise ValueError("response_mask must contain a valid response position")

    with torch.no_grad():
        student_log_probs = student_top_k_log_probs.detach()
        teacher_log_probs = teacher_on_student_log_probs.detach()
        weights = torch.softmax(student_log_probs, dim=-1)
        raw_rewards = (teacher_log_probs - student_log_probs) * weights
        advantages = raw_rewards * response_mask.unsqueeze(-1)
    return TorchTokenRewardAnchor(
        student_top_k_ids=student_top_k_ids.detach(),
        student_top_k_log_probs=student_log_probs,
        teacher_on_student_log_probs=teacher_log_probs,
        student_conditional_weights=weights,
        raw_token_rewards=raw_rewards,
        advantages=advantages,
        response_mask=response_mask.detach(),
        student_temperature=float(student_temperature),
    )


def build_token_reward_from_full_logits(
    student_anchor_logits: torch.Tensor,
    teacher_logits: torch.Tensor,
    response_mask: torch.Tensor,
    *,
    top_k: int,
    student_temperature: float = 1.0,
    teacher_temperature: float = 1.0,
) -> TorchTokenRewardAnchor:
    """Create the synthetic anchor and gather teacher scores on student IDs."""

    if student_anchor_logits.shape != teacher_logits.shape or student_anchor_logits.ndim != 3:
        raise ValueError("student and teacher logits must share [batch, sequence, vocabulary]")
    if top_k <= 0 or top_k > student_anchor_logits.shape[-1]:
        raise ValueError("top_k must be in [1, vocabulary_size]")
    if teacher_temperature <= 0:
        raise ValueError("teacher_temperature must be positive")
    with torch.no_grad():
        student_log_probs = F.log_softmax(student_anchor_logits / student_temperature, dim=-1)
        teacher_log_probs = F.log_softmax(teacher_logits / teacher_temperature, dim=-1)
        student_top_k_log_probs, student_top_k_ids = torch.topk(student_log_probs, k=top_k, dim=-1)
        teacher_on_student = torch.gather(teacher_log_probs, dim=-1, index=student_top_k_ids)
    return build_token_reward_from_selected_ids(
        student_top_k_ids,
        student_top_k_log_probs,
        teacher_on_student,
        response_mask,
        student_temperature=student_temperature,
    )


def token_reward_direct_surrogate_loss(
    current_student_logits: torch.Tensor,
    anchor: TorchTokenRewardAnchor,
    *,
    clip_ratio: float = 0.2,
    clip_ratio_c: float = 3.0,
) -> torch.Tensor:
    """Apply the pinned detached 3D PPO surrogate to current student logits."""

    if current_student_logits.ndim != 3:
        raise ValueError("current student logits must have shape [batch, sequence, vocabulary]")
    if current_student_logits.shape[:2] != anchor.student_top_k_ids.shape[:2]:
        raise ValueError("current student logits do not match the anchor")
    if not 0 < clip_ratio < 1:
        raise ValueError("clip_ratio must be in (0, 1)")
    if clip_ratio_c <= 1:
        raise ValueError("clip_ratio_c must be greater than 1")

    current_log_probs = F.log_softmax(current_student_logits / anchor.student_temperature, dim=-1)
    current_top_k_log_probs = torch.gather(current_log_probs, dim=-1, index=anchor.student_top_k_ids)
    log_ratio = (current_top_k_log_probs - anchor.student_top_k_log_probs).clamp(-20.0, 20.0)
    ratio = torch.exp(log_ratio)
    advantages = anchor.advantages
    loss_unclipped = -advantages * ratio
    loss_clipped = -advantages * ratio.clamp(1 - clip_ratio, 1 + clip_ratio)
    upper = torch.maximum(loss_unclipped, loss_clipped)
    dual_clipped = torch.minimum(-advantages * clip_ratio_c, upper)
    wing_losses = torch.where(advantages < 0, dual_clipped, upper)
    token_losses = wing_losses.sum(dim=-1)
    return (token_losses * anchor.response_mask).sum() / anchor.response_mask.sum()


def run_torch_candidate_parity_gate() -> dict[str, Any]:
    """Compare the Torch compatibility kernel with the independent oracle."""

    student_values = [
        [
            [2.0, 1.0, 0.0, -1.0, -2.0],
            [0.0, 2.0, 1.0, -1.0, -2.0],
            [1.0, 0.0, 2.0, -1.0, -2.0],
        ]
    ]
    teacher_values = [
        [
            [1.0, 2.0, 0.0, -1.0, -2.0],
            [0.0, 1.0, 2.0, -1.0, -2.0],
            [2.0, 0.0, 1.0, -1.0, -2.0],
        ]
    ]
    mask_values = [[1, 1, 0]]
    student = torch.tensor(student_values, dtype=torch.float64, requires_grad=True)
    teacher = torch.tensor(teacher_values, dtype=torch.float64, requires_grad=True)
    response_mask = torch.tensor(mask_values, dtype=torch.float64)
    anchor = build_token_reward_from_full_logits(student, teacher, response_mask, top_k=3)
    loss = token_reward_direct_surrogate_loss(student, anchor)
    loss.backward()

    reference = build_thunlp_token_reward_reference(student_values, teacher_values, mask_values, top_k=3)
    expected_gradient = analytic_gradient_at_anchor(reference)
    expected_gradient_tensor = torch.tensor(expected_gradient, dtype=torch.float64)
    comparisons = {
        "top_k_ids": torch.equal(
            anchor.student_top_k_ids,
            torch.tensor(reference.top_k_ids, dtype=anchor.student_top_k_ids.dtype),
        ),
        "student_top_k_log_probs": torch.allclose(
            anchor.student_top_k_log_probs,
            torch.tensor(reference.student_top_k_log_probs, dtype=anchor.student_top_k_log_probs.dtype),
            atol=1e-12,
            rtol=0,
        ),
        "teacher_on_student_log_probs": torch.allclose(
            anchor.teacher_on_student_log_probs,
            torch.tensor(reference.teacher_on_student_log_probs, dtype=anchor.teacher_on_student_log_probs.dtype),
            atol=1e-12,
            rtol=0,
        ),
        "student_conditional_weights": torch.allclose(
            anchor.student_conditional_weights,
            torch.tensor(reference.student_conditional_weights, dtype=anchor.student_conditional_weights.dtype),
            atol=1e-12,
            rtol=0,
        ),
        "raw_token_rewards": torch.allclose(
            anchor.raw_token_rewards,
            torch.tensor(reference.raw_token_rewards, dtype=anchor.raw_token_rewards.dtype),
            atol=1e-12,
            rtol=0,
        ),
        "advantages_and_mask": torch.allclose(
            anchor.advantages,
            torch.tensor(reference.advantages, dtype=anchor.advantages.dtype),
            atol=1e-12,
            rtol=0,
        ),
        "loss_aggregation": abs(loss.item() - reference.token_mean_loss) <= 1e-12,
        "gradient": torch.allclose(student.grad, expected_gradient_tensor, atol=2e-12, rtol=0),
        "teacher_detached": teacher.grad is None,
    }
    return {
        "status": "PASS_TORCH_COMPATIBILITY_KERNEL" if all(comparisons.values()) else "FAIL",
        "checks": comparisons,
        "metrics": {
            "loss": loss.item(),
            "reference_loss": reference.token_mean_loss,
            "gradient_max_abs_error": (student.grad - expected_gradient_tensor).abs().max().item(),
        },
        "boundary": "kernel parity only; official verl teacher scorer and distributed runtime remain NOT_RUN",
    }
