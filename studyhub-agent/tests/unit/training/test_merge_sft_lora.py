from pathlib import Path

import pytest

from scripts.train.merge_sft_lora import PROCESSOR_CONFIG_FILES, save_model_io_assets


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
