"""Build, load, and roll back a local-only frozen Router RL package."""

from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...paths import BACKEND_ROOT
from ..spec import sha256_file
from .actions import build_action_space
from .evaluate import FORBIDDEN_ENDPOINT_VARS
from .policy import (
    available_action_log_probs,
    decision_prompt,
    encode_prompts,
    final_token_logits,
    load_base_policy,
    load_lora_policy,
    load_processor,
)
from .spec import load_maturity_states


def build_and_exercise_package(
    *,
    repo_root: Path,
    model_path: Path,
    frozen_manifest_path: Path,
    validation_path: Path,
    output_dir: Path,
    device: str,
) -> dict[str, Any]:
    _assert_offline_environment()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite offline package: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen = _read_json(frozen_manifest_path)
    if frozen.get("status") != "frozen_before_test":
        raise ValueError("offline package requires a frozen candidate")
    source_adapter = Path(str(frozen["adapter_path"])).resolve()
    source_weights = source_adapter / "adapter_model.safetensors"
    if sha256_file(source_weights) != frozen["adapter_sha256"]:
        raise ValueError("source adapter no longer matches the frozen manifest")
    export_manifest_path = model_path / "studyhub_export_manifest.json"
    export_manifest = _read_json(export_manifest_path)
    _verify_base_export(model_path, export_manifest)

    config_path = BACKEND_ROOT / "app/core/config.py"
    env_example_path = BACKEND_ROOT / ".env.example"
    configuration_hashes_before = {
        "config.py": sha256_file(config_path),
        ".env.example": sha256_file(env_example_path),
    }
    production_defaults = inspect_production_defaults(config_path, env_example_path)
    if not all(production_defaults.values()):
        raise RuntimeError(f"production defaults are not fully disabled: {production_defaults}")

    package_adapter = output_dir / "adapter"
    shutil.copytree(source_adapter, package_adapter)
    package_weights = package_adapter / "adapter_model.safetensors"
    if sha256_file(package_weights) != frozen["adapter_sha256"]:
        raise RuntimeError("packaged adapter hash differs from the frozen source")
    packaged_files = {
        str(path.relative_to(output_dir)): {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(package_adapter.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "schema_version": "studyhub.agent.router_rl.offline_package.v2",
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "isolated_research_only",
        "frozen_candidate_manifest": str(frozen_manifest_path.resolve()),
        "frozen_candidate_manifest_sha256": sha256_file(frozen_manifest_path),
        "base_model_path": str(model_path.resolve()),
        "base_export_manifest_sha256": sha256_file(export_manifest_path),
        "adapter_sha256": frozen["adapter_sha256"],
        "files": packaged_files,
        "production_defaults": production_defaults,
        "production_configuration_hashes_before": configuration_hashes_before,
        "production_deployment_attempted": False,
        "production_access": False,
        "test_read": False,
        "sealed_read": False,
    }
    manifest_path = output_dir / "package_manifest.json"
    _write_json(manifest_path, manifest)

    states = load_maturity_states(validation_path, splits={"validation"})
    state = min(states, key=lambda value: value.state_id)
    processor = load_processor(model_path)
    candidate_route, candidate_peak = _load_and_predict(
        model_path=model_path,
        adapter_path=package_adapter,
        processor=processor,
        state=state,
        device=device,
    )
    rollback_route, rollback_peak = _load_and_predict(
        model_path=model_path,
        adapter_path=None,
        processor=processor,
        state=state,
        device=device,
    )
    configuration_hashes_after = {
        "config.py": sha256_file(config_path),
        ".env.example": sha256_file(env_example_path),
    }
    checks = {
        "package_adapter_hash": sha256_file(package_weights) == frozen["adapter_sha256"],
        "candidate_package_loaded": bool(candidate_route),
        "rollback_sft_loaded": bool(rollback_route),
        "candidate_route_is_valid": candidate_route in build_action_space(state).routes,
        "rollback_route_is_valid": rollback_route in build_action_space(state).routes,
        "production_defaults_disabled": all(production_defaults.values()),
        "production_configuration_unchanged": configuration_hashes_before
        == configuration_hashes_after,
    }
    result = {
        "schema_version": "studyhub.agent.router_rl.offline_package_exercise.v2",
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
        "canary": {
            "split": "validation",
            "state_id": state.state_id,
            "oracle_route": build_action_space(state).oracle_route,
            "candidate_route": candidate_route,
            "rollback_sft_route": rollback_route,
        },
        "gpu": {
            "candidate_peak_memory_mib": candidate_peak,
            "rollback_peak_memory_mib": rollback_peak,
        },
        "package_manifest_path": str(manifest_path.resolve()),
        "package_manifest_sha256": sha256_file(manifest_path),
        "production_configuration_hashes_after": configuration_hashes_after,
        "production_deployment_attempted": False,
        "production_access": False,
        "test_read": False,
        "sealed_read": False,
    }
    _write_json(output_dir / "load_rollback_exercise.json", result)
    return result


def inspect_production_defaults(config_path: Path, env_example_path: Path) -> dict[str, bool]:
    config = config_path.read_text(encoding="utf-8")
    env_example = env_example_path.read_text(encoding="utf-8")
    return {
        "config_agentic_platform_disabled": "agentic_platform_enabled: bool = False" in config,
        "config_agentic_execution_disabled": "agentic_execution_enabled: bool = False" in config,
        "config_agentic_provider_disabled": 'agentic_model_provider: str = "disabled"' in config,
        "env_agentic_platform_disabled": "STUDYHUB_AGENTIC_PLATFORM_ENABLED=false" in env_example,
        "env_agentic_execution_disabled": "STUDYHUB_AGENTIC_EXECUTION_ENABLED=false" in env_example,
        "env_agentic_provider_disabled": "STUDYHUB_AGENTIC_MODEL_PROVIDER=disabled" in env_example,
    }


def _verify_base_export(model_path: Path, manifest: dict[str, Any]) -> None:
    files = manifest.get("files") or {}
    if not files:
        raise ValueError("base export manifest has no file lock")
    for name, expected in files.items():
        path = model_path / name
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != int(expected["bytes"]):
            raise ValueError(f"base model size changed: {name}")
        if sha256_file(path) != expected["sha256"]:
            raise ValueError(f"base model hash changed: {name}")


def _load_and_predict(
    *,
    model_path: Path,
    adapter_path: Path | None,
    processor: Any,
    state: Any,
    device: str,
) -> tuple[str, float]:
    import torch

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    if adapter_path is None:
        policy = load_base_policy(model_path, device=device, trainable=False)
    else:
        policy = load_lora_policy(
            model_path,
            adapter_path,
            device=device,
            trainable=False,
        )
    policy.eval()
    space = build_action_space(state)
    prompt = decision_prompt(processor, state, space)
    encoded = encode_prompts(
        processor,
        [prompt],
        device=device,
        max_prompt_tokens=4096,
    )
    with torch.no_grad():
        logits = final_token_logits(policy, encoded)[0]
        log_probs = available_action_log_probs(
            logits,
            space=space,
            tokenizer=processor.tokenizer,
            temperature=1.0,
        )
    route = space.routes[int(log_probs.argmax().item())]
    peak = round(torch.cuda.max_memory_allocated() / (1024**2), 3)
    del policy, encoded, logits, log_probs
    gc.collect()
    torch.cuda.empty_cache()
    return route, peak


def _assert_offline_environment() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"offline package exercise refuses configured endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("offline package exercise requires local-only Hugging Face mode")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    result = build_and_exercise_package(
        repo_root=args.repo_root.resolve(),
        model_path=args.model.resolve(),
        frozen_manifest_path=args.frozen_manifest.resolve(),
        validation_path=args.validation.resolve(),
        output_dir=args.output_dir.resolve(),
        device=args.device,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
