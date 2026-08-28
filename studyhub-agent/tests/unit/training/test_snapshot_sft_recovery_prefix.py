from __future__ import annotations

import json
from pathlib import Path

from scripts.train.snapshot_sft_recovery_prefix import snapshot_prefix


def test_snapshot_prefix_atomically_branches_checkpoint(tmp_path: Path) -> None:
    source = tmp_path / "continuous"
    target = tmp_path / "recovered"
    output = tmp_path / "snapshot.json"
    checkpoint = source / "default" / "recover_checkpoint"
    recover_info = source / "recover_info"
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
    (recover_info / "dataloader_info.pkl").write_bytes(b"loader")

    result = snapshot_prefix(
        source,
        target,
        output,
        expected_global_step=1,
    )

    assert result["status"] == "PASS"
    assert result["method"] == "atomic_directory_rename_same_filesystem"
    assert not checkpoint.exists()
    assert (target / "default/recover_checkpoint/__0_0.distcp").read_bytes() == b"checkpoint"
    assert (target / "recover_info/step_info.json").is_file()
    assert (source / "recover_info/step_info.json").is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
