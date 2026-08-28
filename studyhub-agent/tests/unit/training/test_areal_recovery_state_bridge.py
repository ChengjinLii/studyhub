from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import torch

from training.runtime_shims.areal_recovery_state_bridge import (
    _engine_versions,
    _restore_rng_state,
    _save_rng_state,
    _set_engine_versions,
    fingerprint_batch,
)


def test_batch_fingerprint_covers_order_tokens_and_loss_mask() -> None:
    first = [
        {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "loss_mask": torch.tensor([[0, 1, 1]]),
        },
        {
            "input_ids": torch.tensor([[4, 5]]),
            "loss_mask": torch.tensor([[0, 1]]),
        },
    ]
    same = [{key: value.clone() for key, value in row.items()} for row in first]
    changed = [{key: value.clone() for key, value in row.items()} for row in first]
    changed[0]["loss_mask"][0, 1] = 0

    left = fingerprint_batch(first)
    right = fingerprint_batch(same)
    different = fingerprint_batch(changed)

    assert left == right
    assert left["batch_sha256"] != different["batch_sha256"]
    assert left["loss_mask_sha256"] != different["loss_mask_sha256"]


def test_rng_state_round_trip_restores_python_numpy_and_torch(tmp_path: Path) -> None:
    random.seed(7)
    np.random.seed(7)
    torch.manual_seed(7)
    saved = _save_rng_state(tmp_path, rank=0, world_size=1)
    expected = (random.random(), float(np.random.random()), float(torch.rand(1)))

    random.seed(99)
    np.random.seed(99)
    torch.manual_seed(99)
    restored = _restore_rng_state(tmp_path, rank=0, world_size=1)
    actual = (random.random(), float(np.random.random()), float(torch.rand(1)))

    assert saved["sha256"] == restored["sha256"]
    assert actual == expected


def test_engine_version_is_explicitly_restored() -> None:
    class Engine:
        def __init__(self) -> None:
            self.version = 0

        def get_version(self) -> int:
            return self.version

        def set_version(self, value: int) -> None:
            self.version = value

    engine = Engine()

    assert _set_engine_versions({"default": engine}, 165) == {"default": 165}
    assert _engine_versions(engine) == {"default": 165}
