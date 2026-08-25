"""AReaL GRPO driver for the isolated StudyHub Hermes rollout workflow."""

from __future__ import annotations

from areal import PPOTrainer
from areal.api.cli_args import load_expr_config
from areal.dataset import get_custom_dataset
from areal.utils.hf_utils import load_hf_tokenizer

from training.rl.config import StudyHubAgentGRPOConfig


def main(args: list[str]) -> int:
    config, _ = load_expr_config(args, StudyHubAgentGRPOConfig)
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
        "max_turns": config.max_turns,
        "temperature": config.gconfig.temperature,
        "top_p": config.gconfig.top_p,
        "max_completion_tokens": config.gconfig.max_new_tokens,
    }
    eval_workflow_kwargs = {**workflow_kwargs, "temperature": 0.6}
    with PPOTrainer(
        config,
        train_dataset=train_dataset,
        valid_dataset=validation_dataset,
    ) as trainer:
        trainer.train(
            workflow=config.workflow,
            eval_workflow=config.eval_workflow,
            workflow_kwargs=workflow_kwargs,
            eval_workflow_kwargs=eval_workflow_kwargs,
        )
    return 0
