"""AReaL-native SFT driver for a pre-tokenized local DatasetDict."""

from __future__ import annotations

from areal import SFTTrainer
from areal.api.cli_args import SFTConfig, load_expr_config
from areal.dataset import get_custom_dataset
from areal.utils.hf_utils import load_hf_tokenizer


def main(args: list[str]) -> int:
    config, _ = load_expr_config(args, SFTConfig)
    tokenizer = load_hf_tokenizer(config.tokenizer_path)
    train_dataset = get_custom_dataset(
        split="train",
        dataset_config=config.train_dataset,
        tokenizer=tokenizer,
    )
    validation_dataset = get_custom_dataset(
        split="validation",
        dataset_config=config.valid_dataset,
        tokenizer=tokenizer,
    )
    with SFTTrainer(
        config,
        train_dataset=train_dataset,
        valid_dataset=validation_dataset,
    ) as trainer:
        trainer.train()
    return 0
