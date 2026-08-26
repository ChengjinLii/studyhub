#!/usr/bin/env python3
"""Validate the 4B/9B controlled experiment without loading weights or using a GPU."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import pickle
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROXY_ENV = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)

CONTROLLED_V1_LORA_TARGET_MODULES = {
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
}

AREAL_ADMIN_KEY_ENV = "STUDYHUB_AREAL_ADMIN_API_KEY"
PREFLIGHT_ADMIN_KEY = "studyhub-preflight-only-key-not-used-by-a-server"
EXPECTED_TOOL_CALL_PARSER = "qwen3_coder"
MAX_GRPO_MICROBATCH_TOKENS = 4096


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_origin(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def canonical_repository(value: str) -> str:
    return value.removesuffix(".git").rstrip("/")


def count_jsonl(path: Path) -> int:
    with path.open(encoding="utf-8") as stream:
        return sum(1 for line in stream if line.strip())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def check_models(repo_root: Path) -> dict[str, Any]:
    specs = {
        "4b": (
            "Qwen/Qwen3.5-4B",
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
            repo_root / "models/P1/Qwen3.5-4B",
        ),
        "9b": (
            "Qwen/Qwen3.5-9B",
            "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            repo_root / "models/P1/Qwen3.5-9B",
        ),
    }
    result = {}
    for size, (repository, revision, model_dir) in specs.items():
        manifest = json_file(model_dir / "studyhub_download_manifest.json")
        config = json_file(model_dir / "config.json")
        index = json_file(model_dir / "model.safetensors.index.json")
        if manifest["repository"] != repository or manifest["revision"] != revision:
            raise RuntimeError(f"{size} model source or revision mismatch")
        if config.get("model_type") != "qwen3_5":
            raise RuntimeError(f"{size} has unexpected model_type")
        shards = sorted(set(index.get("weight_map", {}).values()))
        if not shards or any(not (model_dir / shard).is_file() for shard in shards):
            raise RuntimeError(f"{size} model shards are incomplete")
        manifest_shards = {row["name"]: int(row["bytes"]) for row in manifest["weight_shards"]}
        actual_shards = {shard: (model_dir / shard).stat().st_size for shard in shards}
        if actual_shards != manifest_shards:
            raise RuntimeError(f"{size} shard sizes differ from the download manifest")
        if sha256(model_dir / "config.json") != manifest["config_sha256"]:
            raise RuntimeError(f"{size} config checksum mismatch")
        if sha256(model_dir / "model.safetensors.index.json") != manifest["index_sha256"]:
            raise RuntimeError(f"{size} index checksum mismatch")
        result[size] = {
            "path": str(model_dir),
            "repository": repository,
            "revision": revision,
            "weight_shards": len(shards),
            "weight_bytes": sum(actual_shards.values()),
        }
    return result


def check_sft_data(project: Path) -> dict[str, Any]:
    from datasets import DatasetDict, load_from_disk

    expected = {"train": 2550, "validation": 300, "test": 150}
    result = {}
    for size in ("4b", "9b"):
        root = project / f"datasets/processed/open_sft_bootstrap_v2_qwen35_{size}"
        manifest = json_file(root / "manifest.json")
        dataset = load_from_disk(str(root / "hf_dataset"))
        if not isinstance(dataset, DatasetDict):
            raise TypeError(f"{size} SFT dataset is not a DatasetDict")
        actual = {split: len(dataset[split]) for split in expected}
        if actual != expected or manifest.get("split_counts") != expected:
            raise RuntimeError(f"{size} SFT split counts mismatch: {actual}")
        if any(int(value) for value in manifest.get("group_overlap", {}).values()):
            raise RuntimeError(f"{size} SFT group leakage detected")
        if manifest.get("token_length", {}).get("max", 0) > 2048:
            raise RuntimeError(f"{size} SFT sequence exceeds 2048 tokens")
        result[size] = {
            "path": str(root),
            "splits": actual,
            "token_length": manifest["token_length"],
            "assistant_token_fraction": manifest["assistant_token_fraction"],
        }
    return result


def check_rl_data(project: Path) -> dict[str, Any]:
    from datasets import DatasetDict, load_from_disk

    from training.rl.budget_contract import (
        CONTROLLED_TASK_MAX_TOOL_CALLS,
        RUNTIME_MAX_MODEL_TURNS,
        validate_task_budget,
    )

    root = project / "datasets/processed/open_agent_rl_v2"
    expected = {"train": 2000, "validation": 400}
    manifest = json_file(root / "manifest.json")
    if manifest.get("schema_version") != "studyhub.open-rl-dataset.v2":
        raise RuntimeError("RL dataset schema is not v2")
    budget_audit = json_file(root / "budget-audit.json")
    if budget_audit.get("status") != "passed" or manifest.get("budget_status") != "passed":
        raise RuntimeError("RL task budget audit did not pass")
    if sha256(root / "budget-audit.json") != manifest.get("budget_audit_sha256"):
        raise RuntimeError("RL task budget audit hash mismatch")
    expected_budget_policy = {
        "runtime_max_model_turns": RUNTIME_MAX_MODEL_TURNS,
        "controlled_task_max_tool_calls": CONTROLLED_TASK_MAX_TOOL_CALLS,
    }
    for key, value in expected_budget_policy.items():
        if manifest.get("budget_policy", {}).get(key) != value:
            raise RuntimeError(f"RL budget policy mismatch: {key}")
    dataset = load_from_disk(str(root / "hf_dataset"))
    if not isinstance(dataset, DatasetDict):
        raise TypeError("RL dataset is not a DatasetDict")
    actual = {split: len(dataset[split]) for split in expected}
    if actual != expected or manifest.get("split_counts") != expected:
        raise RuntimeError(f"RL split counts mismatch: {actual}")
    if manifest.get("task_overlap") != 0:
        raise RuntimeError("RL train/validation task overlap detected")
    oracle_policy = manifest.get("oracle_policy", {})
    if oracle_policy != {
        "public_task_verifier_is_empty": True,
        "gold_answer_in_rollout_context": False,
        "gold_tool_sequence_in_rollout_context": False,
        "gold_evidence_labels_in_rollout_context": False,
    }:
        raise RuntimeError("RL oracle isolation policy is not satisfied")
    for split, count in expected.items():
        if count_jsonl(root / "tasks" / f"{split}.jsonl") != count:
            raise RuntimeError(f"RL public task count mismatch for {split}")
        if count_jsonl(root / "verifiers" / f"{split}.jsonl") != count:
            raise RuntimeError(f"RL hidden verifier count mismatch for {split}")
        tasks = read_jsonl(root / "tasks" / f"{split}.jsonl")
        verifiers = {
            row["task_id"]: row
            for row in read_jsonl(root / "verifiers" / f"{split}.jsonl")
        }
        budget_failures = [
            failure
            for task in tasks
            for failure in validate_task_budget(task, verifiers.get(task["task_id"], {}))
        ]
        if budget_failures:
            raise RuntimeError(f"RL task budget violations: {budget_failures[:3]}")
    environment_count = len(list((root / "environments").glob("*.json")))
    if environment_count != sum(expected.values()):
        raise RuntimeError(f"RL environment count mismatch: {environment_count}")
    return {
        "path": str(root),
        "splits": actual,
        "families": manifest["family_counts"],
        "environment_count": environment_count,
        "oracle_policy": oracle_policy,
        "budget_policy": manifest["budget_policy"],
        "budget_status": "passed",
    }


def check_rl_dev_eval(project: Path) -> dict[str, Any]:
    from datasets import DatasetDict, load_from_disk

    root = project / "datasets/processed/open_agent_rl_dev_eval32_v2"
    source = project / "datasets/processed/open_agent_rl_v2"
    manifest = json_file(root / "manifest.json")
    protocol_path = project / "configs/eval/studyhub-dev-eval-v2.json"
    protocol = json_file(protocol_path)
    if manifest.get("schema_version") != "studyhub.rl-dev-eval-subset.v2":
        raise RuntimeError("RL development evaluation schema is not v2")
    if sha256(source / "manifest.json") != manifest.get("source_manifest_sha256"):
        raise RuntimeError("RL development evaluation source manifest changed")
    dataset = load_from_disk(str(root / "hf_dataset"))
    if not isinstance(dataset, DatasetDict) or set(dataset) != {"validation"}:
        raise TypeError("RL development evaluation must contain only validation")
    rows = list(dataset["validation"])
    if len(rows) != 32 or manifest.get("task_count") != 32:
        raise RuntimeError(f"RL development evaluation count mismatch: {len(rows)}")
    task_path = root / "tasks.jsonl"
    if count_jsonl(task_path) != 32 or sha256(task_path) != manifest.get("task_jsonl_sha256"):
        raise RuntimeError("RL development evaluation task JSONL mismatch")
    task_ids = [str(row["task_id"]) for row in rows]
    if task_ids != manifest.get("task_ids") or len(task_ids) != len(set(task_ids)):
        raise RuntimeError("RL development evaluation task IDs mismatch")
    if any(row.get("verifier") for row in rows):
        raise RuntimeError("RL development evaluation exposes hidden verifier fields")
    train_dataset = load_from_disk(str(source / "hf_dataset"))["train"]
    train_groups = {str(row["metadata"]["group_id"]) for row in train_dataset}
    eval_groups = {str(row["metadata"]["group_id"]) for row in rows}
    if train_groups & eval_groups or manifest.get("rl_train_group_overlap") != 0:
        raise RuntimeError("RL development evaluation overlaps RL train lineage")
    source_manifest = json_file(source / "manifest.json")
    if manifest.get("budget_policy") != source_manifest.get("budget_policy"):
        raise RuntimeError("RL development evaluation budget policy changed")
    for task_id in task_ids:
        if not (source / "environments" / f"{task_id}.json").is_file():
            raise RuntimeError(f"missing evaluation environment: {task_id}")
    subset = protocol.get("subset", {})
    if protocol.get("schema_version") != "studyhub.dev-eval.v2":
        raise RuntimeError("RL development evaluation protocol is not v2")
    expected_subset = {
        "seed": manifest.get("seed"),
        "tasks": 32,
        "rollouts_per_task": 4,
        "source_manifest_sha256": sha256(source / "manifest.json"),
        "manifest_sha256": sha256(root / "manifest.json"),
        "tasks_jsonl_sha256": sha256(task_path),
    }
    for key, value in expected_subset.items():
        if subset.get(key) != value:
            raise RuntimeError(f"RL development evaluation protocol mismatch: subset.{key}")
    budget_contract = protocol.get("budget_contract", {})
    if budget_contract != {
        "runtime_max_model_turns": 6,
        "controlled_task_max_tool_calls": 6,
        "infeasible_tasks_allowed": False,
    }:
        raise RuntimeError("RL development evaluation protocol budget changed")
    generation = protocol.get("generation", {})
    required_generation = {
        "max_turns": 6,
        "deterministic_sampling": True,
        "deterministic_inference": True,
        "max_head_offpolicyness": 0,
    }
    for key, value in required_generation.items():
        if generation.get(key) != value:
            raise RuntimeError(f"RL development evaluation generation mismatch: {key}")
    execution = protocol.get("execution", {})
    if execution != {
        "optimizer_lr": 0.0,
        "require_unchanged_lora": True,
        "exact_rollout_group_size": 4,
    }:
        raise RuntimeError("RL development evaluation execution contract changed")
    return {
        "path": str(root),
        "role": manifest.get("role"),
        "tasks": len(rows),
        "families": manifest.get("family_counts"),
        "sources": manifest.get("source_counts"),
        "train_group_overlap": 0,
        "public_verifier_fields_empty": True,
        "protocol": str(protocol_path),
        "protocol_sha256": sha256(protocol_path),
        "deterministic_sampling": True,
        "deterministic_inference": True,
        "rollouts_per_task": 4,
    }


def check_runtime(project: Path) -> dict[str, Any]:
    from areal.api.cli_args import SFTConfig, load_expr_config

    from training.rl.config import (
        AGENT_ENGINE_MAX_TOKENS,
        AGENT_MAX_TURNS,
        CONTEXT_FINALIZATION_RATIO,
        CONTEXT_SAFETY_MARGIN_TOKENS,
        StudyHubAgentGRPOConfig,
    )
    from training.rl.hermes_workflow import StudyHubHermesWorkflow

    nested_python = shutil.which("python3")
    if nested_python is None or Path(nested_python).resolve() != Path(sys.executable).resolve():
        raise RuntimeError(
            "nested python3 does not resolve to the pinned training interpreter: "
            f"python3={nested_python}, current={sys.executable}"
        )
    nvcc = shutil.which("nvcc")
    deep_gemm_fallback = os.environ.get("STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC") == "1"
    torch_fallbacks = (
        os.environ.get("STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC") == "1"
    )
    metadata_bridge = (
        os.environ.get("STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE") == "1"
    )
    if nvcc is None and deep_gemm_fallback and not torch_fallbacks:
        raise RuntimeError("SGLang torch fallbacks are required when nvcc is unavailable")
    if not metadata_bridge:
        raise RuntimeError(
            "AReaL chat-template metadata bridge is required for bounded final turns"
        )
    from areal.experimental.openai.client import AsyncCompletionsWithReward

    if not getattr(
        AsyncCompletionsWithReward.create,
        "_studyhub_metadata_bridge_v1",
        False,
    ):
        raise RuntimeError("AReaL chat-template metadata bridge was not installed")

    config_root = project / "configs/train"
    admin_key_was_missing = AREAL_ADMIN_KEY_ENV not in os.environ
    if admin_key_was_missing:
        os.environ[AREAL_ADMIN_KEY_ENV] = PREFLIGHT_ADMIN_KEY
    parsed = {}
    try:
        for size in ("4b", "9b"):
            sft_path = config_root / f"open-sft-qwen35-{size}.yaml"
            sft_config, _ = load_expr_config(["--config", str(sft_path)], SFTConfig)
            sft_target_modules = set(sft_config.actor.target_modules)
            if sft_target_modules != CONTROLLED_V1_LORA_TARGET_MODULES:
                raise RuntimeError(
                    f"{size} SFT LoRA targets differ from the controlled-v1 recipe: "
                    f"{sorted(sft_target_modules)}"
                )
            parsed[f"sft_{size}"] = {
                "config": str(sft_path),
                "model": sft_config.actor.path,
                "epochs": sft_config.total_train_epochs,
                "lora_target_modules": sorted(sft_target_modules),
            }
            grpo_path = config_root / f"open-grpo-qwen35-{size}.yaml"
            grpo_config, _ = load_expr_config(
                ["--config", str(grpo_path)], StudyHubAgentGRPOConfig
            )
            eval_config, _ = load_expr_config(
                [
                    "--config",
                    str(grpo_path),
                    "actor.optimizer.lr=0.0",
                    "rollout.deterministic_sampling=true",
                    "rollout.max_head_offpolicyness=0",
                    "sglang.enable_deterministic_inference=true",
                    (
                        "valid_dataset.path="
                        f"{project}/datasets/processed/open_agent_rl_dev_eval32_v2/hf_dataset"
                    ),
                ],
                StudyHubAgentGRPOConfig,
            )
            workflow = StudyHubHermesWorkflow(
                environment_root=grpo_config.environment_root,
                verifier_root=grpo_config.verifier_root,
                hermes_checkout=grpo_config.hermes_checkout,
                reward_artifact_root=grpo_config.reward_artifact_root,
                max_turns=grpo_config.max_turns,
                tokenizer_path=grpo_config.tokenizer_path,
                engine_max_tokens=grpo_config.rollout.agent.engine_max_tokens,
                context_finalization_ratio=grpo_config.context_finalization_ratio,
                context_safety_margin_tokens=(
                    grpo_config.context_safety_margin_tokens
                ),
            )
            if grpo_config.rollout.agent.mode != "subproc":
                raise RuntimeError(f"{size} GRPO must isolate Hermes in subproc mode")
            if grpo_config.rollout.agent.tool_call_parser != EXPECTED_TOOL_CALL_PARSER:
                raise RuntimeError(
                    f"{size} GRPO must use the Qwen3-Coder XML tool parser"
                )
            if grpo_config.rollout.agent.engine_max_tokens != AGENT_ENGINE_MAX_TOKENS:
                raise RuntimeError(
                    f"{size} GRPO must cap each exported interaction at "
                    f"{AGENT_ENGINE_MAX_TOKENS} tokens"
                )
            if grpo_config.max_turns != AGENT_MAX_TURNS:
                raise RuntimeError(
                    f"{grpo_path} must cap frozen Hermes rollouts at "
                    f"{AGENT_MAX_TURNS} model calls"
                )
            if grpo_config.context_finalization_ratio != CONTEXT_FINALIZATION_RATIO:
                raise RuntimeError(
                    f"{size} GRPO context finalization ratio changed from "
                    f"{CONTEXT_FINALIZATION_RATIO}"
                )
            if (
                grpo_config.context_safety_margin_tokens
                != CONTEXT_SAFETY_MARGIN_TOKENS
            ):
                raise RuntimeError(
                    f"{size} GRPO context safety margin changed from "
                    f"{CONTEXT_SAFETY_MARGIN_TOKENS} tokens"
                )
            finalization_threshold = int(
                AGENT_ENGINE_MAX_TOKENS * grpo_config.context_finalization_ratio
            )
            if finalization_threshold >= (
                AGENT_ENGINE_MAX_TOKENS
                - grpo_config.context_safety_margin_tokens
            ):
                raise RuntimeError(
                    f"{size} GRPO finalization threshold leaves no safe final turn"
                )
            if workflow.tokenizer_path != str(Path(grpo_config.tokenizer_path).resolve()):
                raise RuntimeError(f"{size} workflow tokenizer differs from AReaL")
            if workflow.engine_max_tokens != AGENT_ENGINE_MAX_TOKENS:
                raise RuntimeError(f"{size} workflow and AReaL token caps differ")
            if not grpo_config.actor.mask_no_eos_with_zero:
                raise RuntimeError(
                    f"{size} GRPO must zero outcome reward for truncated no-EOS trajectories"
                )
            if grpo_config.rollout.agent.chat_template_type != "hf":
                raise RuntimeError(
                    f"{size} GRPO must use the Hermes-compatible hf chat template"
                )
            if grpo_config.rollout.agent.export_style != "individual":
                raise RuntimeError(
                    f"{size} GRPO must export individually credited Hermes turns"
                )
            if grpo_config.rollout.agent.admin_api_key in {
                "",
                "areal-admin-key",
            }:
                raise RuntimeError(f"{size} GRPO uses an unsafe AReaL admin key")
            if not grpo_config.gconfig.drop_incomplete_group:
                raise RuntimeError(f"{size} GRPO must drop incomplete rollout groups")
            if eval_config.actor.optimizer.lr != 0.0:
                raise RuntimeError(f"{size} evaluation must use a zero optimizer learning rate")
            if not eval_config.rollout.deterministic_sampling:
                raise RuntimeError(f"{size} evaluation must use deterministic request sampling")
            if eval_config.rollout.max_head_offpolicyness != 0:
                raise RuntimeError(f"{size} evaluation must start from an on-policy rollout config")
            if not eval_config.sglang.enable_deterministic_inference:
                raise RuntimeError(f"{size} evaluation must enable deterministic SGLang inference")
            if grpo_config.sglang.max_loras_per_batch != 1:
                raise RuntimeError(f"{size} SGLang must reserve exactly one active LoRA slot")
            if grpo_config.sglang.max_loaded_loras != 1:
                raise RuntimeError(f"{size} SGLang must retain exactly one LoRA adapter")
            if nvcc is None and not grpo_config.sglang.disable_overlap_schedule:
                raise RuntimeError(
                    f"{size} SGLang overlap schedule requires CUDA JIT support on this host"
                )
            if nvcc is None and grpo_config.sglang.sampling_backend != "pytorch":
                raise RuntimeError(
                    f"{size} SGLang sampling must use the PyTorch backend when nvcc is unavailable"
                )
            grpo_target_modules = set(grpo_config.actor.target_modules)
            if grpo_target_modules != CONTROLLED_V1_LORA_TARGET_MODULES:
                raise RuntimeError(
                    f"{size} GRPO LoRA targets differ from the controlled-v1 recipe: "
                    f"{sorted(grpo_target_modules)}"
                )
            if grpo_target_modules != sft_target_modules:
                raise RuntimeError(f"{size} SFT and GRPO LoRA targets differ")
            if grpo_config.actor.mb_spec.max_tokens_per_mb > MAX_GRPO_MICROBATCH_TOKENS:
                raise RuntimeError(f"{size} GRPO actor microbatch exceeds the GPU guard budget")
            if grpo_config.ref.mb_spec.max_tokens_per_mb > MAX_GRPO_MICROBATCH_TOKENS:
                raise RuntimeError(f"{size} GRPO reference microbatch exceeds the GPU guard budget")
            pickle.dumps(workflow)
            parsed[f"grpo_{size}"] = {
                "config": str(grpo_path),
                "model": grpo_config.actor.path,
                "group_size": grpo_config.gconfig.n_samples,
                "drop_incomplete_group": grpo_config.gconfig.drop_incomplete_group,
                "gpus": grpo_config.cluster.n_gpus_per_node,
                "agent_mode": grpo_config.rollout.agent.mode,
                "tool_call_parser": grpo_config.rollout.agent.tool_call_parser,
                "engine_max_tokens": grpo_config.rollout.agent.engine_max_tokens,
                "context_finalization_ratio": (
                    grpo_config.context_finalization_ratio
                ),
                "context_finalization_threshold_tokens": finalization_threshold,
                "context_safety_margin_tokens": (
                    grpo_config.context_safety_margin_tokens
                ),
                "max_turns": grpo_config.max_turns,
                "mask_no_eos_with_zero": grpo_config.actor.mask_no_eos_with_zero,
                "chat_template_type": grpo_config.rollout.agent.chat_template_type,
                "export_style": grpo_config.rollout.agent.export_style,
                "ephemeral_admin_key": True,
                "max_loaded_loras": grpo_config.sglang.max_loaded_loras,
                "max_loras_per_batch": grpo_config.sglang.max_loras_per_batch,
                "overlap_schedule": not grpo_config.sglang.disable_overlap_schedule,
                "sampling_backend": grpo_config.sglang.sampling_backend,
                "actor_microbatch_tokens": grpo_config.actor.mb_spec.max_tokens_per_mb,
                "reference_microbatch_tokens": grpo_config.ref.mb_spec.max_tokens_per_mb,
                "lora_target_modules": sorted(grpo_target_modules),
                "evaluation": {
                    "optimizer_lr": eval_config.actor.optimizer.lr,
                    "deterministic_sampling": eval_config.rollout.deterministic_sampling,
                    "max_head_offpolicyness": eval_config.rollout.max_head_offpolicyness,
                    "deterministic_inference": (
                        eval_config.sglang.enable_deterministic_inference
                    ),
                    "dataset": eval_config.valid_dataset.path,
                },
            }
    finally:
        if admin_key_was_missing:
            os.environ.pop(AREAL_ADMIN_KEY_ENV, None)

    areal_lock = json_file(project / "training/areal/upstream.lock.json")
    areal_checkout = project / ".cache/areal-src"
    if git_head(areal_checkout) != areal_lock["commit"]:
        raise RuntimeError("AReaL checkout differs from upstream.lock.json")
    if canonical_repository(git_origin(areal_checkout)) != canonical_repository(
        areal_lock["repository"]
    ):
        raise RuntimeError("AReaL checkout has an unexpected origin")
    hermes_lock = json_file(project / "integrations/hermes/upstream.lock.json")
    hermes_checkout = project / ".vendor/hermes-agent"
    if git_head(hermes_checkout) != hermes_lock["commit"]:
        raise RuntimeError("Hermes checkout differs from upstream.lock.json")
    if canonical_repository(git_origin(hermes_checkout)) != canonical_repository(
        hermes_lock["repository"]
    ):
        raise RuntimeError("Hermes checkout has an unexpected origin")
    sys.path.insert(0, str(hermes_checkout))
    if importlib.util.find_spec("run_agent") is None:
        raise RuntimeError("pinned Hermes run_agent module is not importable")
    if importlib.util.find_spec("sglang") is None:
        raise RuntimeError("SGLang is missing; run setup_areal_env.sh rl")

    return {
        "python": {
            "executable": sys.executable,
            "nested_python3": nested_python,
        },
        "cuda_toolkit": {
            "nvcc": nvcc,
            "deep_gemm_fallback": deep_gemm_fallback,
            "sglang_torch_fallbacks": torch_fallbacks,
        },
        "areal": {
            "version": importlib.metadata.version("areal"),
            "commit": areal_lock["commit"],
        },
        "sglang": importlib.metadata.version("sglang"),
        "hermes": {
            "commit": hermes_lock["commit"],
            "checkout": str(hermes_checkout),
        },
        "configs": parsed,
    }


def active_trainers() -> list[str]:
    rows = subprocess.run(
        ["ps", "-eo", "pid=,args="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    markers = ("areal train run", "training.sft.open_bootstrap_driver", "training.rl.open_agent_driver")
    return [row.strip() for row in rows if any(marker in row for marker in markers)]


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "artifacts/areal/controlled-experiment-readiness.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = Path(__file__).resolve().parents[2]
    repo_root = project.parent
    for key in PROXY_ENV:
        os.environ.pop(key, None)
    result: dict[str, Any] = {
        "schema_version": "studyhub.controlled-experiment-readiness.v1",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "training_started": False,
    }
    try:
        result["models"] = check_models(repo_root)
        result["sft_data"] = check_sft_data(project)
        result["rl_data"] = check_rl_data(project)
        result["rl_dev_eval"] = check_rl_dev_eval(project)
        result["runtime"] = check_runtime(project)
        result["active_training_processes"] = active_trainers()
        if result["active_training_processes"]:
            raise RuntimeError("training processes are already active")
        result["status"] = "ready"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
