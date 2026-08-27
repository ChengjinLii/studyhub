"""AReaL-native SFT driver for a pre-tokenized local DatasetDict."""

from __future__ import annotations

import os

from areal import SFTTrainer
from areal.api import SaveLoadMeta
from areal.api.cli_args import SFTConfig, load_expr_config
from areal.dataset import get_custom_dataset
from areal.utils.hf_utils import load_hf_tokenizer
from areal.utils.saver import Saver


def _save_initial_lora_weights(trainer: SFTTrainer, config: SFTConfig) -> str | None:
    """Mirror AReaL RLTrainer's initial-LoRA evidence contract for SFT."""
    if not config.actor.use_lora:
        return None
    path = os.path.join(
        Saver.get_model_save_root(
            config.experiment_name,
            config.trial_name,
            config.cluster.fileroot,
            name="actor",
        ),
        "initial_lora",
    )
    adapter_config = os.path.join(path, "adapter_config.json")
    if os.path.isfile(adapter_config):
        return path
    trainer.actor.save(
        meta=SaveLoadMeta(
            path=path,
            weight_format="hf",
            with_optim=False,
            tokenizer=trainer.tokenizer,
            processor=trainer.processor,
            base_model_path=config.actor.path,
        )
    )
    return path


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
        _save_initial_lora_weights(trainer, config)
        trainer.train()
    return 0
