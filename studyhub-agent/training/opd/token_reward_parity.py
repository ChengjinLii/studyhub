"""Numerical contract for THUNLP OPD ``token_reward_direct``.

The pinned THUNLP implementation selects the student's top-k token IDs, scores
those same IDs with the teacher, and creates a detached 3D advantage tensor.
The policy update then sums the k wings at each response position before the
usual token-mean aggregation. This module intentionally has no torch or verl
dependency so it can serve as an independent compatibility oracle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Any

Tensor3 = Sequence[Sequence[Sequence[float]]]
Mask2 = Sequence[Sequence[int]]


def _to_tensor3(value: Tensor3, *, name: str) -> tuple[tuple[tuple[float, ...], ...], ...]:
    tensor = tuple(tuple(tuple(float(item) for item in row) for row in sample) for sample in value)
    if not tensor or not tensor[0] or not tensor[0][0]:
        raise ValueError(f"{name} must be a non-empty [batch, sequence, vocabulary] tensor")
    sequence_length = len(tensor[0])
    vocabulary_size = len(tensor[0][0])
    if any(len(sample) != sequence_length for sample in tensor):
        raise ValueError(f"{name} has inconsistent sequence lengths")
    if any(len(row) != vocabulary_size for sample in tensor for row in sample):
        raise ValueError(f"{name} has inconsistent vocabulary sizes")
    if any(not isfinite(item) for sample in tensor for row in sample for item in row):
        raise ValueError(f"{name} contains a non-finite value")
    return tensor


def _to_mask(
    value: Mask2,
    *,
    batch_size: int,
    sequence_length: int,
) -> tuple[tuple[int, ...], ...]:
    mask = tuple(tuple(int(item) for item in row) for row in value)
    if len(mask) != batch_size or any(len(row) != sequence_length for row in mask):
        raise ValueError("response_mask must match the batch and sequence dimensions")
    if any(item not in {0, 1} for row in mask for item in row):
        raise ValueError("response_mask must be binary")
    if sum(item for row in mask for item in row) == 0:
        raise ValueError("response_mask must contain at least one valid response position")
    return mask


def _log_softmax(row: Sequence[float], temperature: float) -> tuple[float, ...]:
    if not isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    scaled = tuple(float(item) / temperature for item in row)
    maximum = max(scaled)
    log_partition = maximum + log(sum(exp(item - maximum) for item in scaled))
    return tuple(item - log_partition for item in scaled)


def _softmax(row: Sequence[float]) -> tuple[float, ...]:
    maximum = max(row)
    denominator = sum(exp(item - maximum) for item in row)
    return tuple(exp(item - maximum) / denominator for item in row)


def _top_k_ids(row: Sequence[float], top_k: int) -> tuple[int, ...]:
    if top_k <= 0 or top_k > len(row):
        raise ValueError("top_k must be in [1, vocabulary_size]")
    return tuple(sorted(range(len(row)), key=lambda token_id: (-row[token_id], token_id))[:top_k])


@dataclass(frozen=True)
class TokenRewardReference:
    """Detached tensors used by the pinned THUNLP on-policy PPO surrogate."""

    top_k_ids: tuple[tuple[tuple[int, ...], ...], ...]
    student_top_k_log_probs: tuple[tuple[tuple[float, ...], ...], ...]
    teacher_on_student_log_probs: tuple[tuple[tuple[float, ...], ...], ...]
    student_conditional_weights: tuple[tuple[tuple[float, ...], ...], ...]
    raw_token_rewards: tuple[tuple[tuple[float, ...], ...], ...]
    advantages: tuple[tuple[tuple[float, ...], ...], ...]
    student_probabilities: tuple[tuple[tuple[float, ...], ...], ...]
    response_mask: tuple[tuple[int, ...], ...]
    token_losses: tuple[tuple[float, ...], ...]
    token_mean_loss: float
    student_temperature: float
    teacher_temperature: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_k_ids": self.top_k_ids,
            "student_top_k_log_probs": self.student_top_k_log_probs,
            "teacher_on_student_log_probs": self.teacher_on_student_log_probs,
            "student_conditional_weights": self.student_conditional_weights,
            "raw_token_rewards": self.raw_token_rewards,
            "advantages": self.advantages,
            "response_mask": self.response_mask,
            "token_losses": self.token_losses,
            "token_mean_loss": self.token_mean_loss,
            "student_temperature": self.student_temperature,
            "teacher_temperature": self.teacher_temperature,
        }


def build_thunlp_token_reward_reference(
    student_logits: Tensor3,
    teacher_logits: Tensor3,
    response_mask: Mask2,
    *,
    top_k: int,
    student_temperature: float = 1.0,
    teacher_temperature: float = 1.0,
) -> TokenRewardReference:
    """Build the detached ``only_stu``/``student_p`` token rewards.

    ``student_p`` in the source implementation is normalized again over the
    selected k IDs. It is therefore the student's conditional mass inside its
    top-k set, not the original full-vocabulary probability.
    """

    student = _to_tensor3(student_logits, name="student_logits")
    teacher = _to_tensor3(teacher_logits, name="teacher_logits")
    if tuple(map(len, student)) != tuple(map(len, teacher)):
        raise ValueError("student_logits and teacher_logits have different batch dimensions")
    if any(len(s_sample) != len(t_sample) for s_sample, t_sample in zip(student, teacher, strict=True)):
        raise ValueError("student_logits and teacher_logits have different sequence dimensions")
    if any(
        len(s_row) != len(t_row)
        for s_sample, t_sample in zip(student, teacher, strict=True)
        for s_row, t_row in zip(s_sample, t_sample, strict=True)
    ):
        raise ValueError("student_logits and teacher_logits have different vocabulary dimensions")

    batch_size = len(student)
    sequence_length = len(student[0])
    mask = _to_mask(response_mask, batch_size=batch_size, sequence_length=sequence_length)

    all_ids: list[tuple[tuple[int, ...], ...]] = []
    all_student_log_probs: list[tuple[tuple[float, ...], ...]] = []
    all_teacher_log_probs: list[tuple[tuple[float, ...], ...]] = []
    all_weights: list[tuple[tuple[float, ...], ...]] = []
    all_rewards: list[tuple[tuple[float, ...], ...]] = []
    all_advantages: list[tuple[tuple[float, ...], ...]] = []
    all_student_probabilities: list[tuple[tuple[float, ...], ...]] = []
    all_token_losses: list[tuple[float, ...]] = []

    for sample_index, (student_sample, teacher_sample) in enumerate(zip(student, teacher, strict=True)):
        sample_ids: list[tuple[int, ...]] = []
        sample_student_log_probs: list[tuple[float, ...]] = []
        sample_teacher_log_probs: list[tuple[float, ...]] = []
        sample_weights: list[tuple[float, ...]] = []
        sample_rewards: list[tuple[float, ...]] = []
        sample_advantages: list[tuple[float, ...]] = []
        sample_probabilities: list[tuple[float, ...]] = []
        sample_token_losses: list[float] = []

        for token_index, (student_row, teacher_row) in enumerate(
            zip(student_sample, teacher_sample, strict=True)
        ):
            student_log_probs = _log_softmax(student_row, student_temperature)
            teacher_log_probs = _log_softmax(teacher_row, teacher_temperature)
            ids = _top_k_ids(student_row, top_k)
            selected_student = tuple(student_log_probs[token_id] for token_id in ids)
            selected_teacher = tuple(teacher_log_probs[token_id] for token_id in ids)
            weights = _softmax(selected_student)
            rewards = tuple(
                (teacher_log_prob - student_log_prob) * weight
                for student_log_prob, teacher_log_prob, weight in zip(
                    selected_student, selected_teacher, weights, strict=True
                )
            )
            position_mask = mask[sample_index][token_index]
            advantages = tuple(reward * position_mask for reward in rewards)

            sample_ids.append(ids)
            sample_student_log_probs.append(selected_student)
            sample_teacher_log_probs.append(selected_teacher)
            sample_weights.append(weights)
            sample_rewards.append(rewards)
            sample_advantages.append(advantages)
            sample_probabilities.append(tuple(exp(item) for item in student_log_probs))
            sample_token_losses.append(-sum(advantages))

        all_ids.append(tuple(sample_ids))
        all_student_log_probs.append(tuple(sample_student_log_probs))
        all_teacher_log_probs.append(tuple(sample_teacher_log_probs))
        all_weights.append(tuple(sample_weights))
        all_rewards.append(tuple(sample_rewards))
        all_advantages.append(tuple(sample_advantages))
        all_student_probabilities.append(tuple(sample_probabilities))
        all_token_losses.append(tuple(sample_token_losses))

    valid_positions = sum(item for row in mask for item in row)
    loss = sum(
        all_token_losses[sample_index][token_index] * mask[sample_index][token_index]
        for sample_index in range(batch_size)
        for token_index in range(sequence_length)
    ) / valid_positions

    return TokenRewardReference(
        top_k_ids=tuple(all_ids),
        student_top_k_log_probs=tuple(all_student_log_probs),
        teacher_on_student_log_probs=tuple(all_teacher_log_probs),
        student_conditional_weights=tuple(all_weights),
        raw_token_rewards=tuple(all_rewards),
        advantages=tuple(all_advantages),
        student_probabilities=tuple(all_student_probabilities),
        response_mask=mask,
        token_losses=tuple(all_token_losses),
        token_mean_loss=loss,
        student_temperature=student_temperature,
        teacher_temperature=teacher_temperature,
    )


def thunlp_on_policy_surrogate_loss(
    current_student_logits: Tensor3,
    reference: TokenRewardReference,
    *,
    clip_ratio: float = 0.2,
    clip_ratio_c: float = 3.0,
) -> float:
    """Evaluate the pinned 3D PPO surrogate with detached OPD advantages."""

    if not 0 < clip_ratio < 1:
        raise ValueError("clip_ratio must be in (0, 1)")
    if clip_ratio_c <= 1:
        raise ValueError("clip_ratio_c must be greater than 1")
    current = _to_tensor3(current_student_logits, name="current_student_logits")
    if len(current) != len(reference.top_k_ids):
        raise ValueError("current logits do not match the reference batch")

    token_losses: list[float] = []
    valid_positions = sum(item for row in reference.response_mask for item in row)
    for sample_index, sample in enumerate(current):
        if len(sample) != len(reference.top_k_ids[sample_index]):
            raise ValueError("current logits do not match the reference sequence")
        for token_index, row in enumerate(sample):
            log_probs = _log_softmax(row, reference.student_temperature)
            losses = []
            for wing_index, token_id in enumerate(reference.top_k_ids[sample_index][token_index]):
                old_log_prob = reference.student_top_k_log_probs[sample_index][token_index][wing_index]
                log_ratio = max(-20.0, min(20.0, log_probs[token_id] - old_log_prob))
                ratio = exp(log_ratio)
                advantage = reference.advantages[sample_index][token_index][wing_index]
                loss_unclipped = -advantage * ratio
                clipped_ratio = max(1 - clip_ratio, min(1 + clip_ratio, ratio))
                loss_clipped = -advantage * clipped_ratio
                upper = max(loss_unclipped, loss_clipped)
                dual_clipped = min(-advantage * clip_ratio_c, upper)
                losses.append(dual_clipped if advantage < 0 else upper)
            token_losses.append(sum(losses) * reference.response_mask[sample_index][token_index])
    return sum(token_losses) / valid_positions


def analytic_gradient_at_anchor(reference: TokenRewardReference) -> tuple[tuple[tuple[float, ...], ...], ...]:
    """Return dL/d(student logits) at the strict on-policy anchor."""

    valid_positions = sum(item for row in reference.response_mask for item in row)
    gradient: list[tuple[tuple[float, ...], ...]] = []
    for sample_index, probabilities in enumerate(reference.student_probabilities):
        sample_gradient: list[tuple[float, ...]] = []
        for token_index, token_probabilities in enumerate(probabilities):
            advantages = reference.advantages[sample_index][token_index]
            top_k_ids = reference.top_k_ids[sample_index][token_index]
            advantage_by_id = dict(zip(top_k_ids, advantages, strict=True))
            advantage_sum = sum(advantages)
            position_mask = reference.response_mask[sample_index][token_index]
            sample_gradient.append(
                tuple(
                    position_mask
                    * (probability * advantage_sum - advantage_by_id.get(token_id, 0.0))
                    / (reference.student_temperature * valid_positions)
                    for token_id, probability in enumerate(token_probabilities)
                )
            )
        gradient.append(tuple(sample_gradient))
    return tuple(gradient)


def finite_difference_gradient(
    anchor_student_logits: Tensor3,
    reference: TokenRewardReference,
    *,
    epsilon: float = 1e-6,
) -> tuple[tuple[tuple[float, ...], ...], ...]:
    """Numerically differentiate the detached on-policy surrogate."""

    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    anchor = _to_tensor3(anchor_student_logits, name="anchor_student_logits")
    result: list[tuple[tuple[float, ...], ...]] = []
    for sample_index, sample in enumerate(anchor):
        sample_gradient: list[tuple[float, ...]] = []
        for token_index, row in enumerate(sample):
            row_gradient: list[float] = []
            for vocabulary_index in range(len(row)):
                plus = [[list(items) for items in sequence] for sequence in anchor]
                minus = [[list(items) for items in sequence] for sequence in anchor]
                plus[sample_index][token_index][vocabulary_index] += epsilon
                minus[sample_index][token_index][vocabulary_index] -= epsilon
                plus_loss = thunlp_on_policy_surrogate_loss(plus, reference)
                minus_loss = thunlp_on_policy_surrogate_loss(minus, reference)
                row_gradient.append((plus_loss - minus_loss) / (2 * epsilon))
            sample_gradient.append(tuple(row_gradient))
        result.append(tuple(sample_gradient))
    return tuple(result)


def _max_gradient_error(
    left: Tensor3,
    right: Tensor3,
) -> float:
    return max(
        abs(left_item - right_item)
        for left_sample, right_sample in zip(left, right, strict=True)
        for left_row, right_row in zip(left_sample, right_sample, strict=True)
        for left_item, right_item in zip(left_row, right_row, strict=True)
    )


def _teacher_top_k_forward_kl(
    student_logits: Tensor3,
    teacher_logits: Tensor3,
    response_mask: Mask2,
    *,
    top_k: int,
) -> float:
    """Small diagnostic matching official verl's teacher-top-k loss family."""

    student = _to_tensor3(student_logits, name="student_logits")
    teacher = _to_tensor3(teacher_logits, name="teacher_logits")
    mask = _to_mask(response_mask, batch_size=len(student), sequence_length=len(student[0]))
    losses = []
    for sample_index, (student_sample, teacher_sample) in enumerate(zip(student, teacher, strict=True)):
        for token_index, (student_row, teacher_row) in enumerate(
            zip(student_sample, teacher_sample, strict=True)
        ):
            student_log_probs = _log_softmax(student_row, 1.0)
            teacher_log_probs = _log_softmax(teacher_row, 1.0)
            teacher_ids = _top_k_ids(teacher_row, top_k)
            loss = sum(
                exp(teacher_log_probs[token_id])
                * (teacher_log_probs[token_id] - student_log_probs[token_id])
                for token_id in teacher_ids
            )
            losses.append(max(0.0, loss) * mask[sample_index][token_index])
    return sum(losses) / sum(item for row in mask for item in row)


def run_synthetic_parity_gate() -> dict[str, Any]:
    """Run the frozen synthetic loss, mask, and gradient-direction gate."""

    student = (
        (
            (2.0, 1.0, 0.0, -1.0, -2.0),
            (0.0, 2.0, 1.0, -1.0, -2.0),
            (1.0, 0.0, 2.0, -1.0, -2.0),
        ),
    )
    teacher = (
        (
            (1.0, 2.0, 0.0, -1.0, -2.0),
            (0.0, 1.0, 2.0, -1.0, -2.0),
            (2.0, 0.0, 1.0, -1.0, -2.0),
        ),
    )
    response_mask = ((1, 1, 0),)
    reference = build_thunlp_token_reward_reference(student, teacher, response_mask, top_k=3)
    anchor_loss = thunlp_on_policy_surrogate_loss(student, reference)
    analytic = analytic_gradient_at_anchor(reference)
    numerical = finite_difference_gradient(student, reference)
    gradient_error = _max_gradient_error(analytic, numerical)

    step_size = 0.05
    stepped = tuple(
        tuple(
            tuple(value - step_size * gradient for value, gradient in zip(row, gradient_row, strict=True))
            for row, gradient_row in zip(sample, gradient_sample, strict=True)
        )
        for sample, gradient_sample in zip(student, analytic, strict=True)
    )
    stepped_loss = thunlp_on_policy_surrogate_loss(stepped, reference)
    forward_kl_topk_loss = _teacher_top_k_forward_kl(student, teacher, response_mask, top_k=3)

    checks = {
        "anchor_loss_matches_detached_reference": abs(anchor_loss - reference.token_mean_loss) <= 1e-12,
        "masked_position_zero": all(abs(value) <= 1e-12 for value in reference.advantages[0][2]),
        "finite_difference_gradient_matches": gradient_error <= 2e-7,
        "gradient_descent_direction_decreases_surrogate": stepped_loss < anchor_loss,
        "official_teacher_topk_forward_kl_is_not_silently_equivalent": (
            abs(forward_kl_topk_loss - reference.token_mean_loss) > 1e-6
        ),
    }
    status = "PASS_THUNLP_TOKEN_REWARD_DIRECT_MATH" if all(checks.values()) else "FAIL"
    return {
        "schema_version": "studyhub.opd-token-reward-parity.v1",
        "status": status,
        "contract": {
            "adv_estimator": "token_reward_direct",
            "top_k": 3,
            "top_k_strategy": "only_stu",
            "reward_weight_mode": "student_p",
            "loss_aggregation": "sum-k-then-token-mean",
            "advantages_detached": True,
            "scope": "synthetic mathematical parity; runtime/backend parity remains separate",
        },
        "checks": checks,
        "metrics": {
            "reference_token_mean_loss": reference.token_mean_loss,
            "anchor_surrogate_loss": anchor_loss,
            "gradient_max_abs_error": gradient_error,
            "gradient_step_loss": stepped_loss,
            "official_teacher_topk_forward_kl_fixture_loss": forward_kl_topk_loss,
        },
        "reference": reference.to_dict(),
        "analytic_gradient": analytic,
        "finite_difference_gradient": numerical,
        "official_verl_native_equivalence": {
            "sampled_token_k1": False,
            "teacher_top_k_forward_kl": False,
        },
    }
