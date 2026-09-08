#!/usr/bin/env python3
"""Audit an existing OPD checkpoint without fabricating a launcher exit status."""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / "src")]
from scripts.train.merge_sft_lora import sha256  # noqa: E402


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def exported_rewards(rewards, files):
    versions = Counter(int(row["policy_version_directory"]) for row in files)
    if versions != Counter({i: 8 for i in range(300)}):
        raise RuntimeError("exports do not cover eight prompt groups for each of 300 updates")
    expected = Counter(row["task_id"] for row in files)
    accepted = [r for r in rewards if r["task_id"] in expected]
    excluded = [r for r in rewards if r["task_id"] not in expected]
    if Counter(r["task_id"] for r in accepted) != Counter({k: 2 * v for k, v in expected.items()}):
        raise RuntimeError("reward/export task multiplicity mismatch")
    if any(r["reward"]["status"] != "SCORED" for r in accepted):
        raise RuntimeError("infrastructure-failed task appears in training exports")
    for task in {r["task_id"] for r in excluded}:
        group = [r for r in excluded if r["task_id"] == task]
        if len(group) != 2 or not any(r["reward"]["status"] == "INFRA_EXCLUDED" for r in group):
            raise RuntimeError("unexplained excluded reward group")
    return accepted, excluded


def verify_closeout(audit_path, run_path, marker_path):
    audit = read(audit_path)
    marker = read(marker_path)
    if audit.get("status") != "PASS_CHECKPOINT_FOR_EVALUATION":
        raise RuntimeError("closeout audit is not passing")
    if audit["source_run_sha256"] != sha256(run_path):
        raise RuntimeError("original run metadata drift")
    if marker.get("closeout_audit_sha256") != sha256(audit_path):
        raise RuntimeError("completion marker closeout binding drift")
    if audit["final_adapter_sha256"] != marker["checkpoint"]["sha256"]:
        raise RuntimeError("closeout adapter differs from stage marker")
    for path, digest in audit["artifact_hashes"].items():
        if sha256(Path(path)) != digest:
            raise RuntimeError(f"closeout artifact drift: {path}")
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--reward", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--marker", type=Path, required=True)
    args = parser.parse_args()
    audit_path = args.bundle / "recovered-closeout.json"
    if audit_path.exists() or args.marker.exists():
        raise RuntimeError("refusing to replace existing closeout evidence")
    run = read(args.run)
    auth = read(args.authorization)
    log = Path(run["log_file"])
    text = log.read_text(errors="replace")
    steps = [int(x) for x in re.findall(r"Train step (\d+)/500 done\.", text)]
    if steps != list(range(1, 301)):
        raise RuntimeError("log does not prove 300 ordered updates")
    metrics_path = args.bundle / "metrics/trainer.json"
    series = read(metrics_path)["series"]
    if series["update_successful"] != [1.0] * 300 or series["lr"] != [3e-6] * 300:
        raise RuntimeError("optimizer success/LR coverage mismatch")
    files_path = args.bundle / "trajectories/trajectory-files.jsonl"
    files = [json.loads(line) for line in files_path.read_text().splitlines()]
    for row in files:
        if sha256(Path(row["path"])) != row["sha256"]:
            raise RuntimeError("trajectory export hash drift")
    raw = [json.loads(line) for line in args.reward.read_text().splitlines()]
    accepted, excluded = exported_rewards(raw, files)
    accepted_root = args.bundle / "exported-cohort"
    accepted_root.mkdir()
    for name, rows in (("reward-v3.jsonl", accepted), ("excluded-rewards.jsonl", excluded)):
        (accepted_root / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    reconstructed = args.bundle / "reconstructed-stage.json"
    subprocess.run(
        [
            sys.executable,
            str(PROJECT / "scripts/train/record_qwen35_4b_opd_stage.py"),
            "--mode",
            "formal",
            "--trainer-metrics",
            str(metrics_path),
            "--reward-root",
            str(accepted_root),
            "--checkpoint-root",
            str(args.checkpoint_root),
            "--authorization",
            str(args.authorization),
            "--learning-rate",
            "3e-6",
            "--expected-updates",
            "300",
            "--output",
            str(reconstructed),
        ],
        check=True,
    )
    marker = read(reconstructed)

    import torch
    import torch.distributed.checkpoint as dcp
    from safetensors.torch import load_file

    final = Path(marker["checkpoint"]["path"])
    initial = args.checkpoint_root / "actor/initial_lora/adapter_model.safetensors"
    a, b = load_file(str(initial)), load_file(str(final))
    if a.keys() != b.keys() or any(a[k].shape != b[k].shape or not torch.isfinite(b[k]).all() for k in a):
        raise RuntimeError("adapter shapes or finite values invalid")
    changed = sum(not torch.equal(a[k], b[k]) for k in a)
    if not changed:
        raise RuntimeError("no adapter tensors updated")
    recovery = args.checkpoint_root / "default/recover_checkpoint"
    metadata = dcp.FileSystemReader(recovery).read_metadata()
    optimizer_steps = []
    matched_lora = set()
    for index, storage in metadata.storage_data.items():
        path = recovery / storage.relative_path
        if storage.offset < 0 or storage.length <= 0 or storage.offset + storage.length > path.stat().st_size:
            raise RuntimeError("DCP storage extent invalid")
        key = index.fqn
        adapter_key = key.removeprefix("dcp.model.").replace(".default.weight", ".weight")
        is_lora = key.startswith("dcp.model.") and adapter_key in b
        is_step = key.startswith("dcp.optim.state.") and key.endswith(".step")
        if is_lora or is_step:
            with path.open("rb") as stream:
                stream.seek(storage.offset)
                value = torch.load(io.BytesIO(stream.read(storage.length)), map_location="cpu", weights_only=True)
            if is_lora:
                if not torch.equal(value.to(b[adapter_key].dtype), b[adapter_key]):
                    raise RuntimeError("DCP and final adapter differ")
                matched_lora.add(adapter_key)
            else:
                optimizer_steps.append(float(value.item()))
    if matched_lora != set(b) or optimizer_steps != [300.0] * len(b):
        raise RuntimeError("DCP LoRA/optimizer step coverage mismatch")
    recover_info = args.checkpoint_root / "recover_info"
    if read(recover_info / "step_info.json")["global_step"] != 299:
        raise RuntimeError("recovery step mismatch")
    paths = [
        args.run,
        log,
        Path(run["gpu_csv"]),
        args.authorization,
        final,
        initial,
        args.reward,
        metrics_path,
        files_path,
        reconstructed,
        accepted_root / "reward-v3.jsonl",
        accepted_root / "excluded-rewards.jsonl",
        *recovery.iterdir(),
        *recover_info.iterdir(),
    ]
    for relative, field in (
        ("configs/train/qwen35-4b-strict-opd.yaml", "config_sha256"),
        ("benchmarks/studyhub-agent-v2/manifest.json", "benchmark_manifest_sha256"),
        ("training/opd/areal_runtime.py", "opd_runtime_sha256"),
    ):
        path = PROJECT / relative
        if sha256(path) != auth["lineage"][field]:
            raise RuntimeError(f"frozen input drift: {relative}")
        paths.append(path)
    audit = {
        "status": "PASS_CHECKPOINT_FOR_EVALUATION",
        "audited_at": datetime.now(UTC).isoformat(),
        "source_run_sha256": sha256(args.run),
        "original_exit_status": run.get("exit_status"),
        "exit_status_known": run.get("exit_status") is not None,
        "original_metadata_modified": False,
        "training_rerun": False,
        "sealed_used": False,
        "ordered_updates": 300,
        "raw_reward_rows": len(raw),
        "exported_reward_rows": len(accepted),
        "excluded_reward_rows": len(excluded),
        "excluded_reason": "Infra-failed complete group, absent from every training export; not outcome filtering",
        "adapter_tensors": len(b),
        "updated_tensors": changed,
        "finite_tensors": True,
        "dcp_matching_lora_tensors": len(matched_lora),
        "optimizer_steps": sorted(set(optimizer_steps)),
        "recovery_load_resume_experiment": "NOT_RUN",
        "final_adapter_sha256": sha256(final),
        "limitation": (
            "Launcher exit and missing postprocessing cause cannot be reconstructed. "
            "Independent evaluation permitted on verified weights, not a claim of clean process exit."
        ),
        "artifact_hashes": {str(p.resolve()): sha256(p) for p in paths if p.is_file()},
    }
    write(audit_path, audit)
    marker.update(
        closeout_audit_sha256=sha256(audit_path),
        closeout_audit_path=str(audit_path.resolve()),
        original_exit_status=run.get("exit_status"),
        completion_reconstructed=True,
    )
    write(args.marker, marker)
    print(json.dumps({k: v for k, v in audit.items() if k != "artifact_hashes"}, indent=2))


if __name__ == "__main__":
    main()
