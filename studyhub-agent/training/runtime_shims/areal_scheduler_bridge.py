"""Fail-closed scheduler controls for the pinned AReaL SFT runtime."""

from __future__ import annotations

import os
import warnings
from typing import Any

SCHEDULER_TOTAL_STEPS_ENV = "STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS"
RECOVER_SCHEDULER_STEP_ENV = "STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP"


def _required_nonnegative_int(name: str) -> int:
    raw = os.environ.get(name)
    if raw is None:
        raise RuntimeError(f"missing required scheduler bridge variable: {name}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be non-negative, got {value}")
    return value


def align_lr_scheduler(engine: Any, next_global_step: int) -> float:
    """Reconstruct a deterministic LambdaLR position after DCP recovery."""

    scheduler = getattr(engine, "lr_scheduler", None)
    optimizer = getattr(engine, "optimizer", None)
    if scheduler is None or optimizer is None:
        raise RuntimeError("AReaL scheduler recovery requires an initialized optimizer and scheduler")
    if not hasattr(scheduler, "lr_lambdas"):
        raise RuntimeError(f"unsupported scheduler for deterministic recovery: {type(scheduler).__name__}")

    total_steps = _required_nonnegative_int(SCHEDULER_TOTAL_STEPS_ENV)
    if total_steps <= 0 or next_global_step > total_steps:
        raise RuntimeError(f"invalid recovered scheduler position: step={next_global_step}, total={total_steps}")

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Detected call of `lr_scheduler.step\(\)` before `optimizer.step\(\)`",
        )
        warnings.filterwarnings(
            "ignore",
            message="The epoch parameter in `scheduler.step\(\)` was not necessary",
        )
        scheduler.step(next_global_step)

    if int(scheduler.last_epoch) != next_global_step:
        raise RuntimeError(f"scheduler recovery did not reach step {next_global_step}: {scheduler.last_epoch}")
    scheduler_lrs = [float(value) for value in scheduler.get_last_lr()]
    optimizer_lrs = [float(group["lr"]) for group in optimizer.param_groups]
    if scheduler_lrs != optimizer_lrs:
        raise RuntimeError(f"scheduler and optimizer LR differ after recovery: {scheduler_lrs} != {optimizer_lrs}")
    return scheduler_lrs[0]


def install_areal_scheduler_bridge() -> None:
    """Install process-local AReaL scheduler horizon and recovery hooks."""

    total_steps = _required_nonnegative_int(SCHEDULER_TOTAL_STEPS_ENV)
    if total_steps <= 0:
        raise RuntimeError(f"{SCHEDULER_TOTAL_STEPS_ENV} must be positive")

    from areal.api.io_struct import FinetuneSpec
    from areal.engine.fsdp_engine import FSDPEngine

    current_getter = FinetuneSpec.total_train_steps.fget
    if not getattr(current_getter, "_studyhub_scheduler_horizon_v1", False):
        original_getter = current_getter

        def controlled_total_train_steps(self: Any) -> int:
            natural_steps = int(original_getter(self))
            if total_steps < int(self.steps_per_epoch):
                raise RuntimeError(
                    "controlled scheduler horizon cannot be shorter than the real dataloader: "
                    f"horizon={total_steps}, steps_per_epoch={self.steps_per_epoch}"
                )
            if natural_steps <= 0:
                raise RuntimeError(f"invalid natural training horizon: {natural_steps}")
            return total_steps

        controlled_total_train_steps._studyhub_scheduler_horizon_v1 = True  # type: ignore[attr-defined]
        controlled_total_train_steps._studyhub_original_getter = original_getter  # type: ignore[attr-defined]
        FinetuneSpec.total_train_steps = property(controlled_total_train_steps)

    current_loader = FSDPEngine._load_from_dcp
    if not getattr(current_loader, "_studyhub_scheduler_recovery_v1", False):
        original_loader = current_loader

        def load_from_dcp_with_scheduler(self: Any, path: str, with_optim: bool) -> Any:
            result = original_loader(self, path, with_optim)
            raw_step = os.environ.get(RECOVER_SCHEDULER_STEP_ENV)
            if raw_step is None:
                return result
            if not with_optim:
                raise RuntimeError("scheduler recovery requires optimizer-state recovery")
            next_step = _required_nonnegative_int(RECOVER_SCHEDULER_STEP_ENV)
            previous = getattr(self, "_studyhub_scheduler_recovered_step", None)
            if previous is not None and previous != next_step:
                raise RuntimeError(f"scheduler was already recovered to {previous}, refusing {next_step}")
            lr = align_lr_scheduler(self, next_step)
            self._studyhub_scheduler_recovered_step = next_step
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.info(
                    "StudyHub restored LR scheduler to next_global_step=%d, lr=%.12g, horizon=%d",
                    next_step,
                    lr,
                    total_steps,
                )
            return result

        load_from_dcp_with_scheduler._studyhub_scheduler_recovery_v1 = True  # type: ignore[attr-defined]
        load_from_dcp_with_scheduler._studyhub_original_loader = original_loader  # type: ignore[attr-defined]
        FSDPEngine._load_from_dcp = load_from_dcp_with_scheduler
