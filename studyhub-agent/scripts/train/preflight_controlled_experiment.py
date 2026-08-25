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

    root = project / "datasets/processed/open_agent_rl_v1"
    expected = {"train": 2000, "validation": 400}
    manifest = json_file(root / "manifest.json")
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
    environment_count = len(list((root / "environments").glob("*.json")))
    if environment_count != sum(expected.values()):
        raise RuntimeError(f"RL environment count mismatch: {environment_count}")
    return {
        "path": str(root),
        "splits": actual,
        "families": manifest["family_counts"],
        "environment_count": environment_count,
        "oracle_policy": oracle_policy,
    }


def check_runtime(project: Path) -> dict[str, Any]:
    from areal.api.cli_args import SFTConfig, load_expr_config

    from training.rl.config import StudyHubAgentGRPOConfig
    from training.rl.hermes_workflow import StudyHubHermesWorkflow

    config_root = project / "configs/train"
    parsed = {}
    for size in ("4b", "9b"):
        sft_path = config_root / f"open-sft-qwen35-{size}.yaml"
        sft_config, _ = load_expr_config(["--config", str(sft_path)], SFTConfig)
        parsed[f"sft_{size}"] = {
            "config": str(sft_path),
            "model": sft_config.actor.path,
            "epochs": sft_config.total_train_epochs,
        }
        grpo_path = config_root / f"open-grpo-qwen35-{size}.yaml"
        grpo_config, _ = load_expr_config(["--config", str(grpo_path)], StudyHubAgentGRPOConfig)
        workflow = StudyHubHermesWorkflow(
            environment_root=grpo_config.environment_root,
            verifier_root=grpo_config.verifier_root,
            hermes_checkout=grpo_config.hermes_checkout,
            reward_artifact_root=grpo_config.reward_artifact_root,
            max_turns=grpo_config.max_turns,
        )
        if grpo_config.rollout.agent.mode != "subproc":
            raise RuntimeError(f"{size} GRPO must isolate Hermes in subproc mode")
        pickle.dumps(workflow)
        parsed[f"grpo_{size}"] = {
            "config": str(grpo_path),
            "model": grpo_config.actor.path,
            "group_size": grpo_config.gconfig.n_samples,
            "gpus": grpo_config.cluster.n_gpus_per_node,
            "agent_mode": grpo_config.rollout.agent.mode,
        }

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
