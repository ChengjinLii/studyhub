"""Strict THUNLP-style OPD extensions for the pinned AReaL FSDP runtime.

The bridge is deliberately process-local. It leaves upstream AReaL untouched
and adds only the three operations required by canonical ``only_stu`` OPD:
student top-k anchoring, teacher scoring on those IDs, and the detached 3D
policy-surrogate update. Hermes continues to own the actual agent loop.
"""

from __future__ import annotations

import hashlib
import json
import os
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import torch
import torch.distributed as dist

_PATCH_MARKER = "_studyhub_opd_runtime_v1"
_RPC_BROADCAST_PATCH_MARKER = "_studyhub_opd_single_rank_rpc_v1"
_FSDP_OFFLOAD_PATCH_MARKER = "_studyhub_opd_idempotent_offload_v1"
_PROXY_START_PATCH_MARKER = "_studyhub_opd_colocated_proxy_start_v1"
_ADAPTER_ENV = "STUDYHUB_OPD_STUDENT_ADAPTER"
_MAX_DIAGNOSTIC_TURNS = 6
_SPARSE_WING_SEPARATOR = "__wing_"
_SPARSE_TOKEN_FIELDS = (
    "opd_top_k_ids",
    "opd_student_top_k_log_probs",
    "opd_teacher_on_student_log_probs",
    "opd_teacher_top_k_ids",
    "opd_teacher_top_k_log_probs",
)


def _install_single_rank_rpc_broadcast_bridge() -> None:
    """Skip a payload collective when the train engine has only one rank.

    AReaL normally broadcasts RPC arguments from the data-parallel head to the
    model-parallel group. In this experiment the FSDP actor is a single rank,
    so its arguments are already local. Avoiding the no-op collective also
    keeps an offloaded actor from trying to use its paused CUDA communicator.
    Multi-rank engines retain the upstream behavior unchanged.
    """

    from areal.infra.rpc.guard import engine_blueprint

    current = engine_blueprint._should_broadcast_payload
    if getattr(current, _RPC_BROADCAST_PATCH_MARKER, False):
        return

    def should_broadcast_payload(engine: Any, rpc_meta: dict[str, Any] | None) -> bool:
        should_broadcast = current(engine, rpc_meta)
        if not should_broadcast or not getattr(engine, "initialized", False):
            return should_broadcast
        group = getattr(engine, "context_and_model_parallel_group", None)
        if group is None or not dist.is_available() or not dist.is_initialized():
            return should_broadcast
        if dist.get_world_size(group=group) == 1:
            return False
        return should_broadcast

    setattr(should_broadcast_payload, _RPC_BROADCAST_PATCH_MARKER, True)
    should_broadcast_payload._studyhub_upstream = current  # type: ignore[attr-defined]
    engine_blueprint._should_broadcast_payload = should_broadcast_payload


def _install_idempotent_fsdp_offload_bridge(fsdp_engine: type[Any]) -> None:
    """Keep AReaL's colocated initialization from pausing TMS twice."""

    current = fsdp_engine.offload
    if getattr(current, _FSDP_OFFLOAD_PATCH_MARKER, False):
        return

    def offload_once(self: Any) -> Any:
        if getattr(self, "is_offload", False):
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.info("StudyHub skipped redundant FSDP offload")
            return None
        return current(self)

    setattr(offload_once, _FSDP_OFFLOAD_PATCH_MARKER, True)
    offload_once._studyhub_upstream = current  # type: ignore[attr-defined]
    fsdp_engine.offload = offload_once


def _install_colocated_proxy_start_bridge(trainer: Any) -> None:
    """Start AgentWorkflow proxies while their colocated SGLang server is live.

    Pinned AReaL applies its initial colocation offload policy in the trainer
    constructor, then starts AgentWorkflow proxies at the beginning of
    ``train()``. Proxy initialization performs a server health check, which
    cannot pass while that same server is offloaded. Temporarily restoring the
    rollout only around first-time proxy initialization preserves the upstream
    train-loop handoff while avoiding the startup deadlock.
    """

    current = trainer._ensure_proxy_started
    if getattr(current, _PROXY_START_PATCH_MARKER, False):
        return

    def ensure_proxy_started_with_live_rollout(self: Any) -> Any:
        if getattr(self, "_proxy_started", False):
            return current()
        restore_offload = bool(getattr(self, "_should_offload_rollout", False))
        if restore_offload:
            self._onload_rollout()
        try:
            return current()
        finally:
            if restore_offload:
                self._offload_rollout()

    setattr(
        ensure_proxy_started_with_live_rollout,
        _PROXY_START_PATCH_MARKER,
        True,
    )
    ensure_proxy_started_with_live_rollout._studyhub_upstream = current  # type: ignore[attr-defined]
    trainer._ensure_proxy_started = types.MethodType(
        ensure_proxy_started_with_live_rollout,
        trainer,
    )


def assistant_prediction_mask(loss_mask: torch.Tensor) -> torch.Tensor:
    """Align assistant-token labels to the logits that predict them.

    The shift is performed independently on each trajectory. This prevents a
    packed sequence boundary from turning the first token of the next sample
    into a target of the previous sample.
    """

    if loss_mask.ndim not in {1, 2}:
        raise ValueError("loss_mask must have shape [sequence] or [batch, sequence]")
    result = torch.zeros_like(loss_mask)
    result[..., :-1] = loss_mask[..., 1:]
    return result


def prediction_turn_ids(turn_ids: torch.Tensor) -> torch.Tensor:
    """Align structural turn IDs with next-token prediction positions."""

    if turn_ids.ndim not in {1, 2}:
        raise ValueError("turn_ids must have shape [sequence] or [batch, sequence]")
    result = torch.full_like(turn_ids, -1)
    result[..., :-1] = turn_ids[..., 1:]
    return result


def _chunked_selected_log_probs(
    logits: torch.Tensor,
    token_ids: torch.Tensor,
    *,
    temperature: float,
    chunk_size: int = 256,
) -> torch.Tensor:
    if logits.ndim != 2 or token_ids.ndim != 2:
        raise ValueError("logits and token_ids must have shapes [tokens, vocab] and [tokens, k]")
    if logits.shape[0] != token_ids.shape[0]:
        raise ValueError("logits and selected IDs have different token dimensions")
    if not 0 < temperature:
        raise ValueError("temperature must be positive")
    chunks: list[torch.Tensor] = []
    for start in range(0, logits.shape[0], chunk_size):
        end = min(start + chunk_size, logits.shape[0])
        scaled = logits[start:end].float() / temperature
        selected = torch.gather(scaled, dim=-1, index=token_ids[start:end].long())
        chunks.append(selected - torch.logsumexp(scaled, dim=-1, keepdim=True))
    return torch.cat(chunks, dim=0)


def _chunked_top_k_log_probs(
    logits: torch.Tensor,
    *,
    top_k: int,
    temperature: float,
    chunk_size: int = 256,
) -> tuple[torch.Tensor, torch.Tensor]:
    if logits.ndim != 2:
        raise ValueError("logits must have shape [tokens, vocabulary]")
    if not 0 < top_k <= logits.shape[-1]:
        raise ValueError("top_k must be in [1, vocabulary_size]")
    if not 0 < temperature:
        raise ValueError("temperature must be positive")
    ids: list[torch.Tensor] = []
    log_probs: list[torch.Tensor] = []
    for start in range(0, logits.shape[0], chunk_size):
        end = min(start + chunk_size, logits.shape[0])
        scaled = logits[start:end].float() / temperature
        values, token_ids = torch.topk(scaled, k=top_k, dim=-1)
        ids.append(token_ids)
        log_probs.append(values - torch.logsumexp(scaled, dim=-1, keepdim=True))
    return torch.cat(ids, dim=0), torch.cat(log_probs, dim=0)


def _flatten_sequence_lengths(data: list[dict[str, Any]]) -> list[int]:
    """Return one unpadded length for every interaction in every trajectory."""

    lengths: list[int] = []
    for trajectory_index, item in enumerate(data):
        attention_mask = item["attention_mask"]
        if not isinstance(attention_mask, torch.Tensor) or attention_mask.ndim != 2:
            raise ValueError(
                "OPD trajectory attention_mask must have shape "
                f"[interactions, sequence], got trajectory {trajectory_index}: "
                f"{getattr(attention_mask, 'shape', None)}"
            )
        item_lengths = [int(value) for value in attention_mask.long().sum(dim=-1).tolist()]
        if any(length <= 0 for length in item_lengths):
            raise ValueError(f"OPD trajectory {trajectory_index} contains an empty interaction")
        lengths.extend(item_lengths)
    return lengths


def _split_sparse_outputs(
    padded: torch.Tensor,
    meta: Any,
) -> list[torch.Tensor]:
    """Restore interaction tensors to trajectories and trim the sequence axis."""

    group_sizes = [int(value) for value in meta.traj_group_sizes]
    sequence_lengths = [int(value) for value in meta.traj_seqlens]
    if len(group_sizes) != len(sequence_lengths):
        raise RuntimeError("OPD trajectory group and sequence metadata disagree")
    if padded.ndim < 2:
        raise RuntimeError(f"OPD sparse output must include a sequence axis: {padded.shape}")
    if padded.shape[0] != sum(group_sizes):
        raise RuntimeError(
            "OPD sparse output interaction count does not match trajectory metadata: "
            f"{padded.shape[0]} != {sum(group_sizes)}"
        )

    split = list(padded.split(group_sizes, dim=0))
    return [value[:, :sequence_length, ...] for value, sequence_length in zip(split, sequence_lengths, strict=True)]


def _encode_sparse_token_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Expose each top-k wing as an ordinary AReaL token field.

    Pinned AReaL only microbatch-splits tensors whose element count equals
    ``batch * sequence``. A sparse ``[batch, sequence, k]`` tensor is therefore
    treated as a batch-level constant. Encoding each wing as ``[batch,
    sequence]`` lets the upstream splitter, reorderer, packer, and padding code
    preserve token alignment without patching AReaL itself.
    """

    encoded = dict(row)
    attention_mask = encoded.get("attention_mask")
    if not isinstance(attention_mask, torch.Tensor) or attention_mask.ndim != 2:
        raise ValueError("OPD sparse fields require a 2D attention mask")

    for field in _SPARSE_TOKEN_FIELDS:
        value = encoded.get(field)
        if value is None:
            continue
        if not isinstance(value, torch.Tensor) or value.ndim != 3:
            raise ValueError(f"{field} must have shape [interactions, sequence, k]")
        if value.shape[:2] != attention_mask.shape:
            raise ValueError(
                f"{field} does not align with attention_mask: {tuple(value.shape[:2])} != {tuple(attention_mask.shape)}"
            )
        for wing in range(value.shape[-1]):
            wing_key = f"{field}{_SPARSE_WING_SEPARATOR}{wing:03d}"
            if wing_key in encoded:
                raise ValueError(f"duplicate OPD sparse wing field: {wing_key}")
            encoded[wing_key] = value[..., wing]
        del encoded[field]
    return encoded


def _decode_sparse_token_field(
    mb_input: dict[str, Any],
    field: str,
    *,
    expected_wings: int,
) -> torch.Tensor:
    """Reassemble packed AReaL token wings into ``[tokens, k]``."""

    prefix = f"{field}{_SPARSE_WING_SEPARATOR}"
    indexed: list[tuple[int, torch.Tensor]] = []
    for key, value in mb_input.items():
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix) :]
        if not suffix.isdigit() or not isinstance(value, torch.Tensor):
            raise ValueError(f"invalid OPD sparse wing field: {key}")
        if value.ndim != 1:
            raise ValueError(f"packed OPD sparse wing must be 1D: {key}={tuple(value.shape)}")
        indexed.append((int(suffix), value))

    indexed.sort(key=lambda item: item[0])
    indices = [index for index, _ in indexed]
    if indices != list(range(expected_wings)):
        raise RuntimeError(
            f"{field} sparse wings are incomplete: expected {list(range(expected_wings))}, got {indices}"
        )
    lengths = {int(value.shape[0]) for _, value in indexed}
    if len(lengths) != 1:
        raise RuntimeError(f"{field} sparse wings have inconsistent token dimensions")
    return torch.stack([value for _, value in indexed], dim=-1)


def _prepare_opd_input(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for item in data:
        row = dict(item)
        row["opd_response_mask"] = assistant_prediction_mask(row["loss_mask"]).to(dtype=torch.float32)
        if row.get("turn_ids") is not None:
            row["opd_prediction_turn_ids"] = prediction_turn_ids(row["turn_ids"])
        prepared.append(_encode_sparse_token_fields(row))
    return prepared


def _forward_sparse_outputs(
    engine: Any,
    data: list[dict[str, Any]],
    process_logits: Any,
) -> list[dict[str, torch.Tensor]]:
    from areal.engine.core import reorder_and_pad_outputs

    prepared = _prepare_opd_input(data)
    input_batched, meta = engine._normalize_batch_input(prepared)
    if meta is None:
        raise RuntimeError("OPD sparse forward requires per-trajectory batch metadata")
    output_seqlens = _flatten_sequence_lengths(prepared)
    mb_list = engine._prepare_mb_list(input_batched).to(engine.device)
    if mb_list.forward_indices is None or len(output_seqlens) != len(mb_list.forward_indices):
        raise RuntimeError(
            "OPD interaction lengths do not match AReaL forward indices: "
            f"{len(output_seqlens)} != "
            f"{None if mb_list.forward_indices is None else len(mb_list.forward_indices)}"
        )
    collected: dict[str, list[torch.Tensor]] = {}

    def process_output(logits: torch.Tensor, ctx_dict: dict[str, Any]) -> None:
        from areal.engine.fsdp_engine import FSDPTrainContext

        ctx = FSDPTrainContext(**ctx_dict)
        token_count = int(ctx.mb_input["input_ids"].shape[0])
        values = process_logits(logits[:token_count], ctx.mb_input)
        for key, value in values.items():
            collected.setdefault(key, []).append(value)
        return None

    engine.forward_backward_batch(mb_list, process_output, forward_only=True)
    result: dict[str, list[torch.Tensor]] = {}
    for key, values in collected.items():
        padded = reorder_and_pad_outputs(values, output_seqlens, mb_list)
        result[key] = _split_sparse_outputs(padded, meta)
    return [{key: result[key][index] for key in result} for index in range(len(prepared))]


@torch.no_grad()
def _opd_compute_anchor(
    self: Any,
    data: list[dict[str, Any]],
    *,
    top_k: int,
    student_temperature: float,
) -> list[dict[str, torch.Tensor]]:
    self.eval()

    def process(logits: torch.Tensor, mb_input: dict[str, Any]) -> dict[str, torch.Tensor]:
        ids, log_probs = _chunked_top_k_log_probs(
            logits,
            top_k=top_k,
            temperature=student_temperature,
        )
        values = {
            "opd_top_k_ids": ids,
            "opd_student_top_k_log_probs": log_probs,
            "opd_response_mask": mb_input["opd_response_mask"].float(),
        }
        if mb_input.get("opd_prediction_turn_ids") is not None:
            values["opd_prediction_turn_ids"] = mb_input["opd_prediction_turn_ids"].long()
        return values

    return _forward_sparse_outputs(self, data, process)


@torch.no_grad()
def _opd_score_selected(
    self: Any,
    data: list[dict[str, Any]],
    *,
    top_k: int,
    teacher_temperature: float,
) -> list[dict[str, torch.Tensor]]:
    self.eval()

    def process(logits: torch.Tensor, mb_input: dict[str, Any]) -> dict[str, torch.Tensor]:
        student_ids = _decode_sparse_token_field(
            mb_input,
            "opd_top_k_ids",
            expected_wings=top_k,
        ).long()
        teacher_on_student = _chunked_selected_log_probs(
            logits,
            student_ids,
            temperature=teacher_temperature,
        )
        teacher_ids, teacher_log_probs = _chunked_top_k_log_probs(
            logits,
            top_k=top_k,
            temperature=teacher_temperature,
        )
        return {
            "opd_teacher_on_student_log_probs": teacher_on_student,
            "opd_teacher_top_k_ids": teacher_ids,
            "opd_teacher_top_k_log_probs": teacher_log_probs,
        }

    return _forward_sparse_outputs(self, data, process)


def _masked_values(value: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    expanded = mask.bool().unsqueeze(-1).expand_as(value)
    return value[expanded]


def compute_opd_diagnostics(
    student_ids: torch.Tensor,
    student_log_probs: torch.Tensor,
    teacher_on_student: torch.Tensor,
    teacher_ids: torch.Tensor,
    teacher_log_probs: torch.Tensor,
    response_mask: torch.Tensor,
    prediction_turn_ids: torch.Tensor | None = None,
) -> dict[str, torch.Tensor]:
    """Compute the diagnostics required by the frozen OPD contract."""

    if not response_mask.bool().any():
        raise RuntimeError("OPD batch contains no trainable assistant tokens")
    student_conditional_log_probs = torch.log_softmax(student_log_probs, dim=-1)
    teacher_conditional_log_probs = torch.log_softmax(teacher_on_student, dim=-1)
    student_weights = student_conditional_log_probs.exp()
    teacher_weights = teacher_conditional_log_probs.exp()
    raw_rewards = (teacher_on_student - student_log_probs) * student_weights
    valid_rewards = _masked_values(raw_rewards, response_mask)
    student_mass = student_log_probs.exp().sum(dim=-1)
    teacher_on_student_mass = teacher_on_student.exp().sum(dim=-1)
    teacher_mass = teacher_log_probs.exp().sum(dim=-1)
    overlaps = (student_ids.unsqueeze(-1) == teacher_ids.unsqueeze(-2)).any(dim=-1).float()
    valid_positions = response_mask.bool()
    conditional_kl = (student_weights * (student_conditional_log_probs - teacher_conditional_log_probs)).sum(dim=-1)
    student_conditional_entropy = -(student_weights * student_conditional_log_probs).sum(dim=-1)
    teacher_conditional_entropy = -(teacher_weights * teacher_conditional_log_probs).sum(dim=-1)
    result = {
        "opd_token_reward_mean": valid_rewards.mean(),
        "opd_token_reward_std": valid_rewards.std(unbiased=False),
        "opd_token_reward_min": valid_rewards.min(),
        "opd_token_reward_max": valid_rewards.max(),
        "opd_teacher_logprob_advantage": _masked_values(teacher_on_student - student_log_probs, response_mask).mean(),
        "opd_teacher_student_kl": conditional_kl[valid_positions].mean(),
        "opd_overlap_ratio": overlaps[valid_positions].mean(),
        "opd_student_top_k_mass": student_mass[valid_positions].mean(),
        "opd_teacher_on_student_mass": teacher_on_student_mass[valid_positions].mean(),
        "opd_teacher_top_k_mass": teacher_mass[valid_positions].mean(),
        "opd_student_top_k_entropy": student_conditional_entropy[valid_positions].mean(),
        "opd_teacher_on_student_entropy": teacher_conditional_entropy[valid_positions].mean(),
        "opd_scored_tokens": response_mask.sum(),
        "opd_reward_wings": torch.tensor(valid_rewards.numel(), device=valid_rewards.device, dtype=torch.float32),
        "_opd_token_reward_sum": valid_rewards.sum(),
        "_opd_token_reward_sumsq": valid_rewards.square().sum(),
    }
    if prediction_turn_ids is None:
        prediction_turn_ids = torch.full_like(response_mask, -1, dtype=torch.long)
    if prediction_turn_ids.shape != response_mask.shape:
        raise ValueError("prediction turn IDs must have the same shape as response_mask")

    active_turns = 0
    for turn in range(_MAX_DIAGNOSTIC_TURNS):
        prefix = f"opd_turn_{turn}"
        turn_mask = valid_positions & prediction_turn_ids.eq(turn)
        token_count = turn_mask.sum().float()
        wing_values = raw_rewards[turn_mask]
        result[f"{prefix}_scored_tokens"] = token_count
        result[f"{prefix}_reward_wings"] = torch.tensor(
            wing_values.numel(), device=raw_rewards.device, dtype=torch.float32
        )
        if wing_values.numel():
            active_turns += 1
            result[f"{prefix}_token_reward_mean"] = wing_values.mean()
            result[f"{prefix}_token_reward_std"] = wing_values.std(unbiased=False)
            result[f"{prefix}_teacher_student_kl"] = conditional_kl[turn_mask].mean()
            result[f"{prefix}_overlap_ratio"] = overlaps[turn_mask].mean()
            result[f"{prefix}_student_top_k_entropy"] = student_conditional_entropy[turn_mask].mean()
            result[f"{prefix}_teacher_on_student_entropy"] = teacher_conditional_entropy[turn_mask].mean()
            result[f"_{prefix}_token_reward_sum"] = wing_values.sum()
            result[f"_{prefix}_token_reward_sumsq"] = wing_values.square().sum()
        else:
            zero = raw_rewards.new_zeros(())
            result[f"{prefix}_token_reward_mean"] = zero
            result[f"{prefix}_token_reward_std"] = zero
            result[f"{prefix}_teacher_student_kl"] = zero
            result[f"{prefix}_overlap_ratio"] = zero
            result[f"{prefix}_student_top_k_entropy"] = zero
            result[f"{prefix}_teacher_on_student_entropy"] = zero
            result[f"_{prefix}_token_reward_sum"] = zero
            result[f"_{prefix}_token_reward_sumsq"] = zero
    result["opd_active_turns"] = torch.tensor(active_turns, device=response_mask.device, dtype=torch.float32)
    return result


def aggregate_opd_diagnostics(
    rows: list[dict[str, torch.Tensor]],
) -> dict[str, float]:
    """Merge microbatch diagnostics without averaging unequal token counts."""

    if not rows:
        raise ValueError("at least one OPD diagnostic row is required")
    total_tokens = sum(float(row["opd_scored_tokens"].item()) for row in rows)
    total_wings = sum(float(row["opd_reward_wings"].item()) for row in rows)
    if total_tokens <= 0 or total_wings <= 0:
        raise RuntimeError("OPD diagnostics contain no scored assistant tokens")

    reward_sum = sum(float(row["_opd_token_reward_sum"].item()) for row in rows)
    reward_sumsq = sum(float(row["_opd_token_reward_sumsq"].item()) for row in rows)
    reward_mean = reward_sum / total_wings
    result = {
        "opd_token_reward_mean": reward_mean,
        "opd_token_reward_std": max(reward_sumsq / total_wings - reward_mean**2, 0.0) ** 0.5,
        "opd_token_reward_min": min(float(row["opd_token_reward_min"].item()) for row in rows),
        "opd_token_reward_max": max(float(row["opd_token_reward_max"].item()) for row in rows),
        "opd_scored_tokens": total_tokens,
        "opd_reward_wings": total_wings,
    }
    token_weighted = (
        "opd_teacher_logprob_advantage",
        "opd_teacher_student_kl",
        "opd_overlap_ratio",
        "opd_student_top_k_mass",
        "opd_teacher_on_student_mass",
        "opd_teacher_top_k_mass",
        "opd_student_top_k_entropy",
        "opd_teacher_on_student_entropy",
    )
    for key in token_weighted:
        result[key] = (
            sum(float(row[key].item()) * float(row["opd_scored_tokens"].item()) for row in rows) / total_tokens
        )

    active_turns = 0
    for turn in range(_MAX_DIAGNOSTIC_TURNS):
        prefix = f"opd_turn_{turn}"
        turn_tokens = sum(float(row[f"{prefix}_scored_tokens"].item()) for row in rows)
        turn_wings = sum(float(row[f"{prefix}_reward_wings"].item()) for row in rows)
        result[f"{prefix}_scored_tokens"] = turn_tokens
        result[f"{prefix}_reward_wings"] = turn_wings
        if turn_tokens <= 0 or turn_wings <= 0:
            result[f"{prefix}_token_reward_mean"] = 0.0
            result[f"{prefix}_token_reward_std"] = 0.0
            result[f"{prefix}_teacher_student_kl"] = 0.0
            result[f"{prefix}_overlap_ratio"] = 0.0
            continue
        active_turns += 1
        turn_sum = sum(float(row[f"_{prefix}_token_reward_sum"].item()) for row in rows)
        turn_sumsq = sum(float(row[f"_{prefix}_token_reward_sumsq"].item()) for row in rows)
        turn_mean = turn_sum / turn_wings
        result[f"{prefix}_token_reward_mean"] = turn_mean
        result[f"{prefix}_token_reward_std"] = max(turn_sumsq / turn_wings - turn_mean**2, 0.0) ** 0.5
        for suffix in (
            "teacher_student_kl",
            "overlap_ratio",
            "student_top_k_entropy",
            "teacher_on_student_entropy",
        ):
            key = f"{prefix}_{suffix}"
            result[key] = (
                sum(float(row[key].item()) * float(row[f"{prefix}_scored_tokens"].item()) for row in rows) / turn_tokens
            )
    result["opd_active_turns"] = float(active_turns)
    return result


def _opd_update(
    self: Any,
    data: list[dict[str, Any]],
    *,
    top_k: int,
    student_temperature: float,
    eps_clip: float,
    clip_ratio_c: float,
) -> dict[str, float]:
    from areal.engine.core import compute_total_loss_weight
    from areal.engine.fsdp_engine import FSDPTrainContext

    self.train()
    self._ensure_ready()
    self.optimizer_zero_grad()
    prepared = _prepare_opd_input(data)
    input_batched, _ = self._normalize_batch_input(prepared)
    mb_list = self._prepare_mb_list(input_batched).to(self.device)

    def loss_weight_fn(mb: dict[str, Any]) -> torch.Tensor:
        return mb["opd_response_mask"].count_nonzero()

    total_weight = compute_total_loss_weight(mb_list, loss_weight_fn, self.dp_group)
    diagnostic_rows: list[dict[str, torch.Tensor]] = []
    loss_numerator_rows: list[torch.Tensor] = []
    loss_weight_rows: list[torch.Tensor] = []

    def process_output(logits: torch.Tensor, ctx_dict: dict[str, Any]) -> torch.Tensor:
        ctx = FSDPTrainContext(**ctx_dict)
        mb = ctx.mb_input
        token_count = int(mb["input_ids"].shape[0])
        ids = _decode_sparse_token_field(
            mb,
            "opd_top_k_ids",
            expected_wings=top_k,
        ).long()
        old_log_probs = (
            _decode_sparse_token_field(
                mb,
                "opd_student_top_k_log_probs",
                expected_wings=top_k,
            )
            .float()
            .detach()
        )
        teacher_log_probs = (
            _decode_sparse_token_field(
                mb,
                "opd_teacher_on_student_log_probs",
                expected_wings=top_k,
            )
            .float()
            .detach()
        )
        response_mask = mb["opd_response_mask"].float()
        current = _chunked_selected_log_probs(
            logits[:token_count],
            ids,
            temperature=student_temperature,
        )
        student_weights = torch.softmax(old_log_probs, dim=-1)
        advantages = ((teacher_log_probs - old_log_probs) * student_weights * response_mask.unsqueeze(-1)).detach()
        log_ratio = (current - old_log_probs).clamp(-20.0, 20.0)
        ratio = log_ratio.exp()
        loss_unclipped = -advantages * ratio
        loss_clipped = -advantages * ratio.clamp(1 - eps_clip, 1 + eps_clip)
        upper = torch.maximum(loss_unclipped, loss_clipped)
        dual_clipped = torch.minimum(-advantages * clip_ratio_c, upper)
        wing_losses = torch.where(advantages < 0, dual_clipped, upper)
        token_losses = wing_losses.sum(dim=-1)
        local_weight = response_mask.sum()
        loss = (token_losses * response_mask).sum() / local_weight.clamp(min=1)
        scaled_loss = loss * (local_weight / total_weight) * self.parallel_helper.dp_size
        loss_numerator_rows.append((loss.detach() * local_weight).float())
        loss_weight_rows.append(local_weight.detach().float())
        diagnostic_rows.append(
            compute_opd_diagnostics(
                ids,
                old_log_probs,
                teacher_log_probs,
                _decode_sparse_token_field(
                    mb,
                    "opd_teacher_top_k_ids",
                    expected_wings=top_k,
                ).long(),
                _decode_sparse_token_field(
                    mb,
                    "opd_teacher_top_k_log_probs",
                    expected_wings=top_k,
                ).float(),
                response_mask,
                mb["opd_prediction_turn_ids"].long(),
            )
        )
        return scaled_loss

    self.forward_backward_batch(mb_list, process_output, forward_only=False)
    stats = {key: float(value) for key, value in self.optimizer_step().items()}
    loss_totals = torch.stack(
        [
            torch.stack(loss_numerator_rows).sum(),
            torch.stack(loss_weight_rows).sum(),
        ]
    )
    torch.distributed.all_reduce(loss_totals, group=self.dp_group)
    if loss_totals[1] <= 0:
        raise RuntimeError("OPD update contains no trainable assistant tokens")
    stats["opd_loss"] = float((loss_totals[0] / loss_totals[1]).item())
    stats.update(aggregate_opd_diagnostics(diagnostic_rows))
    return stats


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_existing_adapter(self: Any) -> None:
    adapter_path = os.environ.get(_ADAPTER_ENV, "").strip()
    if not adapter_path or not self.config.use_lora:
        return
    path = Path(adapter_path).resolve()
    config_path = path / "adapter_config.json"
    weights_path = path / "adapter_model.safetensors"
    if not config_path.is_file() or not weights_path.is_file():
        raise FileNotFoundError(f"incomplete OPD student adapter: {path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    expected = {
        "r": int(self.config.lora_rank),
        "lora_alpha": int(self.config.lora_alpha),
    }
    actual = {key: int(payload.get(key, -1)) for key in expected}
    if actual != expected:
        raise RuntimeError(f"OPD adapter/config mismatch: expected={expected}, actual={actual}")
    expected_targets = set(map(str, self.config.target_modules))
    actual_target_value = payload.get("target_modules", [])
    if isinstance(actual_target_value, str):
        actual_targets = {actual_target_value}
    else:
        actual_targets = set(map(str, actual_target_value))
    if actual_targets != expected_targets:
        raise RuntimeError(
            f"OPD adapter target-module mismatch: expected={sorted(expected_targets)}, actual={sorted(actual_targets)}"
        )

    # Nonzero ranks hold meta tensors here. AReaL later broadcasts rank 0's
    # full PEFT state as part of its native FSDP2 initialization.
    if int(getattr(self, "rank", 0)) != 0:
        self._studyhub_opd_adapter = {
            "path": str(path),
            "adapter_sha256": _sha256(weights_path),
            "loaded_by_rank0_broadcast": True,
            "target_modules": sorted(actual_targets),
        }
        return

    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    state = load_file(str(weights_path), device="cpu")
    result = set_peft_model_state_dict(self.model, state, adapter_name="default")
    missing = list(getattr(result, "missing_keys", []))
    unexpected = list(getattr(result, "unexpected_keys", []))
    unexpected_lora = [key for key in unexpected if "lora_" in key]
    if unexpected_lora:
        raise RuntimeError(f"unexpected LoRA keys while loading M2 adapter: {unexpected_lora[:8]}")
    loaded = sum(1 for key in state if "lora_" in key)
    if loaded == 0:
        raise RuntimeError("M2 adapter contains no LoRA tensors")
    nonzero = sum(int(torch.count_nonzero(value).item()) for key, value in state.items() if "lora_" in key)
    if nonzero == 0:
        raise RuntimeError("M2 adapter LoRA tensors are all zero")
    self._studyhub_opd_adapter = {
        "path": str(path),
        "adapter_sha256": _sha256(weights_path),
        "lora_tensors": loaded,
        "lora_nonzero_values": nonzero,
        "missing_key_count": len(missing),
        "loaded_by_rank0_broadcast": False,
        "target_modules": sorted(actual_targets),
    }


def install_areal_opd_bridge() -> None:
    """Install the OPD worker methods on the pinned AReaL process."""

    from areal.engine.fsdp_engine import FSDPEngine, FSDPPPOActor

    _install_single_rank_rpc_broadcast_bridge()
    _install_idempotent_fsdp_offload_bridge(FSDPEngine)
    if getattr(FSDPPPOActor, _PATCH_MARKER, False):
        return

    original_prepare = FSDPEngine._prepare_mb_inputs

    def prepare_without_opd_payload(self: Any, mb_item: Any) -> Any:
        inputs, ctx = original_prepare(self, mb_item)
        for key in tuple(inputs):
            if key.startswith("opd_"):
                inputs.pop(key, None)
        return inputs, ctx

    original_peft = FSDPEngine._apply_peft_wrapper

    def apply_peft_and_load_adapter(self: Any) -> None:
        original_peft(self)
        _load_existing_adapter(self)

    FSDPEngine._prepare_mb_inputs = prepare_without_opd_payload
    FSDPEngine._apply_peft_wrapper = apply_peft_and_load_adapter
    FSDPPPOActor.opd_compute_anchor = _opd_compute_anchor
    FSDPPPOActor.opd_score_selected = _opd_score_selected
    FSDPPPOActor.opd_update = _opd_update
    setattr(FSDPPPOActor, _PATCH_MARKER, True)


def install_opd_controller_hooks(trainer: Any, config: Any) -> None:
    """Route the stock PPO trainer through strict OPD operations.

    The outer AReaL lifecycle remains unchanged: Hermes rollout, checkpointing,
    LoRA weight publication, and recovery all continue to use upstream code.
    Only teacher scoring, advantage preparation, and the actor update are
    replaced for this explicitly configured run.
    """

    if trainer.teacher is None:
        raise RuntimeError("strict OPD requires a frozen teacher engine")
    if not hasattr(trainer.actor, "_custom_function_call"):
        raise RuntimeError("strict OPD currently requires the pinned AReaL v1 controller")

    _install_colocated_proxy_start_bridge(trainer)

    top_k = int(config.opd_top_k)
    student_temperature = float(config.opd_student_temperature)
    teacher_temperature = float(config.opd_teacher_temperature)
    eps_clip = float(config.opd_eps_clip)
    clip_ratio_c = float(config.opd_clip_ratio_c)

    def teacher_scores(_teacher: Any, data: list[dict[str, Any]]) -> list[torch.Tensor]:
        if trainer._should_offload_actor:
            trainer._onload_model(trainer.actor, role="actor_opd_anchor")
        try:
            anchors = trainer.actor._custom_function_call(
                "opd_compute_anchor",
                data,
                top_k=top_k,
                student_temperature=student_temperature,
                rpc_meta={"broadcast": True},
            )
        finally:
            if trainer._should_offload_actor:
                trainer._offload_model(trainer.actor, role="actor_opd_anchor")
        if len(anchors) != len(data):
            raise RuntimeError("student anchor count does not match rollout batch")
        for trajectory, anchor in zip(data, anchors, strict=True):
            trajectory.update(anchor)

        scores = _teacher._custom_function_call(
            "opd_score_selected",
            data,
            top_k=top_k,
            teacher_temperature=teacher_temperature,
            rpc_meta={"broadcast": True},
        )
        if len(scores) != len(data):
            raise RuntimeError("teacher score count does not match rollout batch")
        result: list[torch.Tensor] = []
        for trajectory, score in zip(data, scores, strict=True):
            trajectory.update(score)
            result.append(score["opd_teacher_on_student_log_probs"])
        return result

    def identity_advantages(_actor: Any, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        required = {
            "opd_top_k_ids",
            "opd_student_top_k_log_probs",
            "opd_teacher_on_student_log_probs",
            "opd_teacher_top_k_ids",
            "opd_teacher_top_k_log_probs",
            "opd_response_mask",
            "opd_prediction_turn_ids",
        }
        for index, trajectory in enumerate(data):
            missing = required - trajectory.keys()
            if missing:
                raise RuntimeError(f"trajectory {index} lacks OPD tensors: {sorted(missing)}")
        return data

    def opd_update(_actor: Any, data: list[dict[str, Any]]) -> None:
        from areal.utils import stats_tracker

        result = _actor._custom_function_call(
            "opd_update",
            data,
            top_k=top_k,
            student_temperature=student_temperature,
            eps_clip=eps_clip,
            clip_ratio_c=clip_ratio_c,
            rpc_meta={"broadcast": True},
        )
        if isinstance(result, Sequence) and not isinstance(result, dict):
            result = result[0]
        if not isinstance(result, dict):
            raise RuntimeError(f"unexpected OPD update result: {type(result).__name__}")
        stats_tracker.scalar(**{key: float(value) for key, value in result.items()})

    trainer.teacher.compute_logp = types.MethodType(teacher_scores, trainer.teacher)
    trainer.actor.compute_advantages = types.MethodType(identity_advantages, trainer.actor)
    trainer.actor.ppo_update = types.MethodType(opd_update, trainer.actor)
