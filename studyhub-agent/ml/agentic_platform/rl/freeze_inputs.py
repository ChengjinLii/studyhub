"""Freeze policy, reference, data, reward, and runtime-constraint inputs for RL."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..paths import BACKEND_ROOT, WORKSPACE_ROOT
from .spec import sha256_file

ROOT = Path(__file__).resolve().parents[3]


def freeze_inputs(*, config_path: Path, output_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model = Path(config["model_path"]).resolve()
    adapter = Path(config["sft_adapter_path"]).resolve()
    dataset = Path(config["dataset_path"]).resolve()
    if config.get("production_access_allowed") is not False or config.get("final_holdout_allowed") is not False:
        raise ValueError("RL pilot config must explicitly disable production and final holdout access")
    required = [
        model / "config.json",
        model / "model.safetensors.index.json",
        model / "tokenizer_config.json",
        adapter / "adapter_config.json",
        adapter / "adapter_model.safetensors",
        dataset,
        dataset.parent / "manifest.json",
        dataset.parent / "audit.json",
        config_path,
        BACKEND_ROOT / "app/services/agent_router_constraint_service.py",
        ROOT / "ml/agentic_platform/rl/reward.py",
        ROOT / "ml/agentic_platform/rl/environment.py",
        ROOT / "ml/agentic_platform/rl/trainer.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing frozen RL input: {missing}")
    audit = json.loads((dataset.parent / "audit.json").read_text(encoding="utf-8"))
    if audit.get("passed") is not True or audit.get("material_split_leaks") or audit.get("query_split_leaks"):
        raise ValueError("RL dataset audit is not clean")
    result = {
        "schema_version": "studyhub.agent.router_rl.input_lock.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "policy": {
            "base_model_path": str(model),
            "base_config_sha256": sha256_file(model / "config.json"),
            "base_weight_index_sha256": sha256_file(model / "model.safetensors.index.json"),
            "tokenizer_config_sha256": sha256_file(model / "tokenizer_config.json"),
            "sft_adapter_path": str(adapter),
            "sft_adapter_sha256": sha256_file(adapter / "adapter_model.safetensors"),
        },
        "reference_policy": {
            "frozen_from_same_sft_adapter": True,
            "adapter_sha256": sha256_file(adapter / "adapter_model.safetensors"),
            "updated_by_optimizer": False,
        },
        "dataset": {
            "path": str(dataset),
            "sha256": sha256_file(dataset),
            "manifest_sha256": sha256_file(dataset.parent / "manifest.json"),
            "audit_sha256": sha256_file(dataset.parent / "audit.json"),
            "states": audit["states"],
            "material_split_leaks": audit["material_split_leaks"],
            "query_split_leaks": audit["query_split_leaks"],
        },
        "implementation_sha256": {
            str(
                path.relative_to(ROOT)
                if path.is_relative_to(ROOT)
                else path.relative_to(WORKSPACE_ROOT)
            ): sha256_file(path)
            for path in required[-4:]
        },
        "config": {"path": str(config_path), "sha256": sha256_file(config_path)},
        "isolation": {
            "network_mode": "offline",
            "production_api_called": False,
            "production_database_accessed": False,
            "production_oss_write_called": False,
            "paid_material_used": False,
            "development_diagnostic_read": False,
            "final_holdout_read": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = freeze_inputs(config_path=args.config.resolve(), output_path=args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
