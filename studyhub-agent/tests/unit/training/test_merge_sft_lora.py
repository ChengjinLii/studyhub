import hashlib
import json
from pathlib import Path

import pytest

from scripts.train.merge_sft_lora import (
    PROCESSOR_CONFIG_FILES,
    completion_lineage,
    save_model_io_assets,
)


class _SavedAsset:
    def __init__(self, files: tuple[str, ...]) -> None:
        self.files = files

    def save_pretrained(self, output: Path) -> None:
        output.mkdir(parents=True, exist_ok=True)
        for name in self.files:
            (output / name).write_text("fixture\n", encoding="utf-8")


class _Tokenizer:
    @classmethod
    def from_pretrained(cls, *_args, **_kwargs) -> _SavedAsset:
        return _SavedAsset(("tokenizer.json", "tokenizer_config.json"))


class _CompositeProcessor(_SavedAsset):
    def __init__(self, *, include_video_config: bool = True) -> None:
        super().__init__(("processor_config.json",))
        self.image_processor = _SavedAsset(("preprocessor_config.json",))
        video_files = ("video_preprocessor_config.json",) if include_video_config else ()
        self.video_processor = _SavedAsset(video_files)


class _Processor:
    @classmethod
    def from_pretrained(cls, *_args, **_kwargs) -> _CompositeProcessor:
        return _CompositeProcessor()


class _IncompleteProcessor:
    @classmethod
    def from_pretrained(cls, *_args, **_kwargs) -> _CompositeProcessor:
        return _CompositeProcessor(include_video_config=False)


def test_save_model_io_assets_preserves_qwen_processor_configs(tmp_path: Path) -> None:
    files = save_model_io_assets(
        tmp_path / "base",
        tmp_path / "merged",
        tokenizer_class=_Tokenizer,
        processor_class=_Processor,
    )

    assert set(PROCESSOR_CONFIG_FILES).issubset(files)
    assert "tokenizer.json" in files


def test_save_model_io_assets_rejects_incomplete_processor(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="video_preprocessor_config.json"):
        save_model_io_assets(
            tmp_path / "base",
            tmp_path / "merged",
            tokenizer_class=_Tokenizer,
            processor_class=_IncompleteProcessor,
        )


def test_completion_lineage_requires_and_hashes_formal_checkpoint(tmp_path: Path) -> None:
    adapter = tmp_path / "checkpoint/adapter_model.safetensors"
    adapter.parent.mkdir()
    adapter.write_bytes(b"adapter")
    marker = tmp_path / "complete.json"
    marker.write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "mode": "formal",
                "training_trial": "sft1",
                "expected_optimizer_updates": 2100,
                "final_global_step": 2099,
                "checkpoint": {
                    "path": str(adapter),
                    "sha256": hashlib.sha256(b"adapter").hexdigest(),
                },
                "dataset_manifest_sha256": "d" * 64,
                "benchmark_manifest_sha256": "b" * 64,
                "git_commit": "c" * 40,
                "sealed_used": False,
                "rl_started": False,
            }
        ),
        encoding="utf-8",
    )

    lineage = completion_lineage(marker)

    assert lineage["final_global_step"] == 2099
    assert lineage["checkpoint_sha256"] == hashlib.sha256(b"adapter").hexdigest()
    assert lineage["completion_marker_sha256"] == hashlib.sha256(marker.read_bytes()).hexdigest()


def test_completion_lineage_rejects_nonformal_or_drifted_checkpoint(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter_model.safetensors"
    adapter.write_bytes(b"drifted")
    marker = tmp_path / "complete.json"
    marker.write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "mode": "smoke",
                "checkpoint": {"path": str(adapter), "sha256": "0" * 64},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="completed formal"):
        completion_lineage(marker)

    value = json.loads(marker.read_text(encoding="utf-8"))
    value["mode"] = "formal"
    value["sealed_used"] = False
    value["rl_started"] = False
    marker.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash drift"):
        completion_lineage(marker)
