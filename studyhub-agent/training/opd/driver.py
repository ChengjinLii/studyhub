"""AReaL driver for strict THUNLP-style OPD over real Hermes rollouts."""

from __future__ import annotations

from pathlib import Path

from areal import PPOTrainer
from areal.api.cli_args import load_expr_config
from areal.dataset import get_custom_dataset
from areal.utils.hf_utils import load_hf_tokenizer

from training.opd.areal_runtime import install_opd_controller_hooks
from training.opd.config import StudyHubOPDConfig


def main(args: list[str]) -> int:
    config, _ = load_expr_config(args, StudyHubOPDConfig)
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
    workflow_kwargs = {
        "environment_root": config.environment_root,
        "verifier_root": config.verifier_root,
        "hermes_checkout": config.hermes_checkout,
        "reward_artifact_root": config.reward_artifact_root,
        "experiment_name": config.experiment_name,
        "trial_name": config.trial_name,
        "run_kind": "train",
        "seed": config.seed,
        "max_turns": config.max_turns,
        "tokenizer_path": config.tokenizer_path,
        "engine_max_tokens": config.rollout.agent.engine_max_tokens,
        "context_finalization_ratio": config.context_finalization_ratio,
        "context_safety_margin_tokens": config.context_safety_margin_tokens,
        "temperature": config.gconfig.temperature,
        "top_p": config.gconfig.top_p,
        "max_completion_tokens": config.gconfig.max_new_tokens,
    }
    eval_workflow_kwargs = {
        **workflow_kwargs,
        "reward_artifact_root": str(Path(config.reward_artifact_root) / "validation"),
        "run_kind": "validation",
        "temperature": config.eval_gconfig.temperature,
        "top_p": config.eval_gconfig.top_p,
        "max_completion_tokens": config.eval_gconfig.max_new_tokens,
    }
    with PPOTrainer(
        config,
        train_dataset=train_dataset,
        valid_dataset=validation_dataset,
    ) as trainer:
        install_opd_controller_hooks(trainer, config)
        trainer.train(
            workflow=config.workflow,
            eval_workflow=config.eval_workflow,
            workflow_kwargs=workflow_kwargs,
            eval_workflow_kwargs=eval_workflow_kwargs,
        )
    return 0
