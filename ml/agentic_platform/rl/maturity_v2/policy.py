"""Local-only constrained-token policy helpers for Router RL maturity v2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import (
    ACTION_ROUTES,
    RouterActionSpace,
    action_token_ids,
    decision_messages,
)
from .spec import MaturityRouterState

LORA_TARGET_MODULES = (
    "in_proj_qkv",
    "in_proj_z",
    "in_proj_a",
    "down_proj",
    "q_proj",
    "k_proj",
    "out_proj",
    "gate_proj",
    "up_proj",
    "v_proj",
    "in_proj_b",
    "o_proj",
)


def load_processor(model_path: Path):
    from transformers import AutoProcessor

    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        local_files_only=True,
    )
    processor.tokenizer.padding_side = "left"
    processor.tokenizer.truncation_side = "left"
    action_token_ids(processor.tokenizer)
    return processor


def load_base_policy(model_path: Path, *, device: str, trainable: bool):
    import torch
    from transformers import AutoModelForMultimodalLM

    model = AutoModelForMultimodalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        trust_remote_code=True,
        local_files_only=True,
        low_cpu_mem_usage=True,
    ).to(device)
    model.train(trainable)
    for parameter in model.parameters():
        parameter.requires_grad_(trainable)
    return model


def create_lora_policy(
    model_path: Path,
    *,
    device: str,
    rank: int,
    alpha: int | None = None,
    dropout: float = 0.05,
    gradient_checkpointing: bool = True,
):
    from peft import LoraConfig, get_peft_model

    base = load_base_policy(model_path, device=device, trainable=False)
    config = LoraConfig(
        r=rank,
        lora_alpha=alpha or rank * 2,
        lora_dropout=dropout,
        bias="none",
        target_modules=list(LORA_TARGET_MODULES),
        task_type="CAUSAL_LM",
    )
    policy = get_peft_model(base, config)
    policy.train()
    if gradient_checkpointing:
        policy.gradient_checkpointing_enable()
        policy.enable_input_require_grads()
    return policy


def load_lora_policy(
    model_path: Path,
    adapter_path: Path,
    *,
    device: str,
    trainable: bool,
    gradient_checkpointing: bool = False,
):
    from peft import PeftModel

    base = load_base_policy(model_path, device=device, trainable=False)
    policy = PeftModel.from_pretrained(base, adapter_path, is_trainable=trainable)
    policy.train(trainable)
    if trainable and gradient_checkpointing:
        policy.gradient_checkpointing_enable()
        policy.enable_input_require_grads()
    return policy


def decision_prompt(processor: Any, state: MaturityRouterState, space: RouterActionSpace) -> str:
    return processor.apply_chat_template(
        decision_messages(state, space),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def encode_prompts(
    processor: Any,
    prompts: list[str],
    *,
    device: str,
    max_prompt_tokens: int,
) -> dict[str, Any]:
    encoded = processor(
        text=prompts,
        padding=True,
        truncation=True,
        max_length=max_prompt_tokens,
        return_tensors="pt",
    )
    return {
        key: value.to(device) if hasattr(value, "to") else value
        for key, value in encoded.items()
    }


def final_token_logits(model: Any, encoded: dict[str, Any]):
    outputs = model(**encoded, use_cache=False)
    return outputs.logits[:, -1, :].float()


def available_action_logits(
    full_logits: Any,
    *,
    space: RouterActionSpace,
    tokenizer: Any,
):
    import torch

    token_ids = action_token_ids(tokenizer)
    indices = torch.tensor(
        [token_ids[route] for route in space.routes],
        dtype=torch.long,
        device=full_logits.device,
    )
    return full_logits.index_select(-1, indices)


def available_action_log_probs(
    full_logits: Any,
    *,
    space: RouterActionSpace,
    tokenizer: Any,
    temperature: float,
):
    import torch

    logits = available_action_logits(full_logits, space=space, tokenizer=tokenizer)
    return torch.log_softmax(logits / temperature, dim=-1)


def true_token_entropy(full_logits: Any):
    import torch

    log_probs = torch.log_softmax(full_logits.float(), dim=-1)
    probabilities = log_probs.exp()
    return -(probabilities * log_probs).sum(dim=-1)


def action_entropy(action_log_probs: Any):
    return -(action_log_probs.exp() * action_log_probs).sum(dim=-1)


def trainable_parameter_count(model: Any) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def validate_global_action_order() -> None:
    if len(ACTION_ROUTES) != 6 or len(set(ACTION_ROUTES)) != 6:
        raise ValueError("the constrained Router action vocabulary must contain six unique routes")
