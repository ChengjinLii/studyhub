from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

import pytest
import torch
import torch.distributed.checkpoint as dcp

from scripts.train.snapshot_sft_recovery_prefix import snapshot_prefix


def _source_tree(root: Path) -> Path:
    checkpoint = root / "default" / "recover_checkpoint"
    recover_info = root / "recover_info"
    checkpoint.mkdir(parents=True)
    recover_info.mkdir(parents=True)
    (checkpoint / ".metadata").write_bytes(b"metadata")
    (checkpoint / "__0_0.distcp").write_bytes(b"checkpoint")
    (recover_info / "step_info.json").write_text(
        json.dumps(
            {
                "epoch": 0,
                "epoch_step": 1,
                "global_step": 1,
                "steps_per_epoch": 2100,
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "checkpoint_info.json",
        "evaluator_info.json",
        "saver_info.json",
        "stats_logger_info.json",
    ):
        (recover_info / name).write_text("{}\n", encoding="utf-8")
    (recover_info / "dataloader_info.pkl").write_bytes(b"loader")
    return checkpoint


def test_snapshot_prefix_is_non_destructive_and_hash_identical(tmp_path: Path) -> None:
    source = tmp_path / "continuous"
    target = tmp_path / "recovered"
    output = tmp_path / "snapshot.json"
    checkpoint = _source_tree(source)

    result = snapshot_prefix(
        source,
        target,
        output,
        expected_global_step=1,
        stability_interval_seconds=0,
        require_dcp_metadata_load=False,
    )

    assert result["status"] == "PASS"
    assert result["method"] == "paused_non_destructive_copy_atomic_publish"
    assert result["source_preserved"] is True
    assert result["source_inventory"] == result["target_inventory"]
    assert checkpoint.is_dir()
    assert (source / "default/recover_checkpoint/__0_0.distcp").read_bytes() == b"checkpoint"
    assert (target / "default/recover_checkpoint/__0_0.distcp").read_bytes() == b"checkpoint"
    assert (target / "recover_info/step_info.json").is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"


def test_snapshot_prefix_rejects_incomplete_recover_info(tmp_path: Path) -> None:
    source = tmp_path / "continuous"
    target = tmp_path / "recovered"
    output = tmp_path / "snapshot.json"
    _source_tree(source)
    (source / "recover_info/dataloader_info.pkl").unlink()

    with pytest.raises(RuntimeError, match="recover_info is incomplete"):
        snapshot_prefix(
            source,
            target,
            output,
            expected_global_step=1,
            stability_interval_seconds=0,
            require_dcp_metadata_load=False,
        )

    assert not target.exists()


def test_snapshot_prefix_loads_real_dcp_metadata_on_both_sides(tmp_path: Path) -> None:
    source = tmp_path / "continuous"
    target = tmp_path / "recovered"
    output = tmp_path / "snapshot.json"
    checkpoint = _source_tree(source)
    shutil.rmtree(checkpoint)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dcp.save({"value": torch.arange(3)}, checkpoint_id=checkpoint)

    result = snapshot_prefix(
        source,
        target,
        output,
        expected_global_step=1,
        stability_interval_seconds=0,
        require_dcp_metadata_load=True,
    )

    assert result["dcp_metadata_load"]["source"]["status"] == "PASS"
    assert result["dcp_metadata_load"]["target"]["status"] == "PASS"
    assert result["dcp_metadata_load"]["source"]["state_dict_metadata_entries"] == 1
