from __future__ import annotations

import copy

import pytest

from scripts.train.record_open_only_sft_completion import validate_lr_audit


def _authorization() -> dict:
    return {
        "recipe": {
            "scheduler": "cosine",
            "scheduler_total_steps": 5456,
            "learning_rate": 2e-5,
            "warmup_fraction": 0.03,
        },
        "completion_contract": {
            "expected_scheduler_total_steps": 5456,
            "expected_warmup_steps": 163,
        },
    }


def _audit() -> dict:
    return {
        "status": "PASS",
        "contract": {
            "scheduler": "cosine",
            "scheduler_total_steps": 5456,
            "base_lr": 2e-5,
            "warmup_fraction": 0.03,
            "warmup_steps": 163,
            "expected_updates": 2100,
            "expected_start_step": 0,
        },
        "coverage": {
            "observed_updates": 2100,
            "first_global_step": 0,
            "last_global_step": 2099,
        },
        "mismatch_count": 0,
        "failures": [],
    }


def test_completion_accepts_only_the_authorized_lr_contract() -> None:
    validate_lr_audit(_audit(), _authorization(), expected_updates=2100)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("contract", "scheduler_total_steps", 2100),
        ("contract", "warmup_steps", 63),
        ("contract", "expected_updates", 2099),
        ("coverage", "last_global_step", 2098),
        ("root", "mismatch_count", 1),
    ],
)
def test_completion_rejects_a_self_consistent_but_unauthorized_audit(
    section: str,
    key: str,
    value: int,
) -> None:
    audit = copy.deepcopy(_audit())
    if section == "root":
        audit[key] = value
    else:
        audit[section][key] = value

    with pytest.raises(RuntimeError):
        validate_lr_audit(audit, _authorization(), expected_updates=2100)
