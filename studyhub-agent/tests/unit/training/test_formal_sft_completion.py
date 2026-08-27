import hashlib
import json
from pathlib import Path

import pytest

from scripts.train.record_formal_sft_completion import build_marker


def _args(tmp_path: Path, *, exit_status: int = 0, global_step: int = 4):
    checkpoint = tmp_path / f"default/epoch0epochstep{global_step}globalstep{global_step}/adapter_model.safetensors"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"adapter")
    metadata = tmp_path / "attempt.run.json"
    metadata.write_text(
        json.dumps(
            {
                "exit_status": exit_status,
                "config": {"overrides": ["trial_name=formal-r16-seed-1"]},
                "dataset_manifest_sha256": "d" * 64,
                "benchmark": {
                    "status": "FROZEN_FOR_BASELINE",
                    "sealed_content_used": False,
                    "sha256": "b" * 64,
                },
                "git": {"commit": "c" * 40},
            }
        ),
        encoding="utf-8",
    )
    return type(
        "Args",
        (),
        {
            "run_metadata": metadata,
            "checkpoint_root": tmp_path,
            "expected_updates": 5,
        },
    )()


def test_completion_marker_requires_exact_final_step(tmp_path: Path) -> None:
    args = _args(tmp_path)

    marker = build_marker(args)

    assert marker["status"] == "COMPLETE"
    assert marker["training_trial"] == "formal-r16-seed-1"
    assert marker["final_global_step"] == 4
    assert marker["checkpoint"]["sha256"] == hashlib.sha256(b"adapter").hexdigest()


def test_completion_marker_rejects_partial_or_failed_run(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="did not exit successfully"):
        build_marker(_args(tmp_path / "failed", exit_status=70))

    with pytest.raises(RuntimeError, match="expected 4"):
        build_marker(_args(tmp_path / "partial", global_step=3))
