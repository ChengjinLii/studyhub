#!/usr/bin/env python3
"""Run the frozen public tau2 15-task replication with official semantics."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.benchmark.external.run_bfcl_replication import (
    GpuTelemetry,
    absolute_executable,
    canonical_sha256,
    compute_pids,
    read_json,
    sha256,
    write_json,
)
from scripts.benchmark.run_9b_base_eval import resolve_model_artifact, wait_for_server

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = Path(
    "/data/chengjin/studyhub/studyhub-agent/artifacts/external-benchmarks/sources/tau2/"
    "fc0055dc4e0a316c3f83133267fbd6faaa770992"
)
DEFAULT_OUTPUT_ROOT = Path("/data/chengjin/studyhub/studyhub-agent/artifacts/external-benchmarks/runs")
DEFAULT_SERVER_PYTHON = Path("/data/chengjin/studyhub/studyhub-agent/.venv-train/bin/python")
DEFAULT_TAU2_PYTHON = Path("/data/chengjin/studyhub/studyhub-agent/artifacts/external-benchmarks/venvs/tau2/bin/python")
PROXY_ENVIRONMENT_KEYS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


def git_value(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT.parent,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_replication_contract(contract: dict[str, Any], source_root: Path) -> dict[str, list[str]]:
    if contract.get("status") != "FROZEN_BEFORE_M1_COMPLETION":
        raise RuntimeError("tau2 replication selection is not frozen before M1 completion")
    boundary = contract.get("claim_boundary", {})
    if boundary.get("fresh_holdout_used") is not False or boundary.get("training_or_tuning_input") is not False:
        raise RuntimeError("tau2 replication claim boundary permits holdout or training use")
    if boundary.get("official_full_leaderboard_score") is not False:
        raise RuntimeError("tau2 partial replication is mislabeled as an official leaderboard score")

    protocol = contract.get("protocol", {})
    if protocol.get("agent", {}).get("enable_thinking") is not False:
        raise RuntimeError("tau2 agent thinking must remain disabled")
    if protocol.get("user", {}).get("enable_thinking") is not False:
        raise RuntimeError("tau2 user-simulator thinking must remain disabled")
    if protocol.get("enforce_communication_protocol") is not True:
        raise RuntimeError("tau2 communication protocol must remain enforced")

    benchmark = contract.get("benchmark", {})
    marker = read_json(source_root / ".studyhub-external-lock.json")
    if marker.get("resolved_commit") != benchmark.get("resolved_commit") or marker.get("tree") != benchmark.get(
        "git_tree"
    ):
        raise RuntimeError("tau2 source revision drift")

    selection = contract.get("selection", {})
    tasks = selection.get("tasks")
    if not isinstance(tasks, dict) or set(tasks) != {"airline", "retail", "telecom"}:
        raise RuntimeError("tau2 replication must contain the three frozen domains")
    normalized: dict[str, list[str]] = {}
    flattened: list[tuple[str, str]] = []
    for domain, values in tasks.items():
        if not isinstance(values, list) or not values:
            raise RuntimeError(f"tau2 domain has no task IDs: {domain}")
        ids = [str(value) for value in values]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"tau2 domain contains duplicate task IDs: {domain}")
        normalized[str(domain)] = ids
        flattened.extend((str(domain), task_id) for task_id in ids)
    if len(flattened) != int(selection["expected_tasks"]) or len(flattened) != len(set(flattened)):
        raise RuntimeError("tau2 replication task count or global uniqueness drift")
    if canonical_sha256(normalized) != selection["canonical_sha256"]:
        raise RuntimeError("tau2 replication task ID hash drift")

    data_root = source_root / "data/tau2/domains"
    for domain, task_ids in normalized.items():
        path = data_root / domain / "tasks.json"
        expected_hash = selection["source_file_sha256"][domain]
        if not path.is_file() or sha256(path) != expected_hash:
            raise RuntimeError(f"tau2 {domain} task source drift")
        rows = json.loads(path.read_text(encoding="utf-8"))
        available = {str(row["id"]) for row in rows}
        missing = sorted(set(task_ids) - available)
        if missing:
            raise RuntimeError(f"tau2 {domain} task IDs are missing: {missing}")
    return normalized


def local_tau2_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in PROXY_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    environment.update(
        {
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "OPENAI_API_KEY": "EMPTY",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    return environment


def llm_arguments(*, port: int, temperature: float, max_tokens: int) -> dict[str, Any]:
    return {
        "temperature": temperature,
        "api_base": f"http://127.0.0.1:{port}/v1",
        "api_key": "EMPTY",
        "max_tokens": max_tokens,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }


def tau2_command(
    *,
    tau2_python: Path,
    domain: str,
    task_ids: list[str],
    save_to: Path,
    agent_port: int,
    user_port: int,
    protocol: dict[str, Any],
) -> list[str]:
    agent_args = llm_arguments(
        port=agent_port,
        temperature=float(protocol["agent"]["temperature"]),
        max_tokens=int(protocol["agent"]["max_tokens"]),
    )
    user_args = llm_arguments(
        port=user_port,
        temperature=float(protocol["user"]["temperature"]),
        max_tokens=int(protocol["user"]["max_tokens"]),
    )
    command = [
        str(tau2_python),
        "-m",
        "tau2.cli",
        "run",
        "--domain",
        domain,
        "--agent",
        "llm_agent",
        "--agent-llm",
        "openai/default",
        "--agent-llm-args",
        json.dumps(agent_args, separators=(",", ":")),
        "--user",
        "user_simulator",
        "--user-llm",
        "openai/default",
        "--user-llm-args",
        json.dumps(user_args, separators=(",", ":")),
        "--task-split-name",
        "base",
        "--task-ids",
        *task_ids,
        "--num-trials",
        str(protocol["num_trials"]),
        "--max-steps",
        str(protocol["max_steps"]),
        "--max-errors",
        str(protocol["max_errors"]),
        "--timeout",
        str(protocol["simulation_timeout_seconds"]),
        "--save-to",
        str(save_to),
        "--max-concurrency",
        str(protocol["max_concurrency"]),
        "--seed",
        str(protocol["seed"]),
        "--max-retries",
        str(protocol["max_retries"]),
        "--retry-delay",
        str(protocol["retry_delay_seconds"]),
        "--enforce-communication-protocol",
        "--log-level",
        "INFO",
    ]
    return command


def launch_server(
    *,
    python: Path,
    model: Path,
    gpu: int,
    port: int,
    log_path: Path,
    server: dict[str, Any],
) -> tuple[subprocess.Popen[str], Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("w", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": str(gpu),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC": "1",
            "STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC": "1",
            "PYTHONPATH": ":".join(
                [
                    str(PROJECT_ROOT / "training/runtime_shims"),
                    str(PROJECT_ROOT),
                    str(PROJECT_ROOT / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ).rstrip(":"),
        }
    )
    command = [
        str(python),
        "-m",
        "sglang.launch_server",
        "--model-path",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--served-model-name",
        "default",
        "--api-key",
        "EMPTY",
        "--dtype",
        "bfloat16",
        "--context-length",
        str(server["context_length"]),
        "--mem-fraction-static",
        str(server["mem_fraction_static"]),
        "--max-running-requests",
        str(server["max_running_requests"]),
        "--tool-call-parser",
        str(server["tool_call_parser"]),
        "--reasoning-parser",
        str(server["reasoning_parser"]),
        "--sampling-backend",
        "pytorch",
        "--disable-overlap-schedule",
    ]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    return process, stream


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    for signum, timeout in ((signal.SIGINT, 30), (signal.SIGTERM, 10), (signal.SIGKILL, 10)):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            continue
    raise RuntimeError(f"failed to terminate SGLang process group: {process.pid}")


def run_logged(command: list[str], *, cwd: Path, environment: dict[str, str], log_path: Path) -> None:
    with log_path.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if completed.returncode:
        raise RuntimeError(f"official tau2 command failed ({completed.returncode}); see {log_path}")


def summarize_domain(path: Path, expected_ids: list[str]) -> dict[str, Any]:
    value = read_json(path)
    simulations = value.get("simulations")
    if not isinstance(simulations, list):
        raise RuntimeError(f"tau2 result has no simulations: {path}")
    observed_ids = [str(row["task_id"]) for row in simulations]
    if len(observed_ids) != len(expected_ids) or set(observed_ids) != set(expected_ids):
        raise RuntimeError(f"tau2 result task IDs drifted: {path}")
    rewards = [float((row.get("reward_info") or {}).get("reward", 0.0)) for row in simulations]
    terminations = Counter(str(row.get("termination_reason", "unknown")) for row in simulations)
    durations = [float(row.get("duration") or 0.0) for row in simulations]
    return {
        "reward_sum": sum(rewards),
        "mean_reward": sum(rewards) / len(rewards),
        "tasks": len(rewards),
        "terminations": dict(sorted(terminations.items())),
        "mean_duration_seconds": sum(durations) / len(durations),
        "results_sha256": sha256(path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/eval/qwen35-4b-tau2-replication-v1.json",
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--agent-gpu", type=int, default=0)
    parser.add_argument("--user-gpu", type=int, default=1)
    parser.add_argument("--agent-port", type=int, default=18144)
    parser.add_argument("--user-port", type=int, default=18145)
    parser.add_argument("--server-python", type=Path, default=DEFAULT_SERVER_PYTHON)
    parser.add_argument("--tau2-python", type=Path, default=DEFAULT_TAU2_PYTHON)
    parser.add_argument("--server-timeout", type=int, default=1200)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if git_value("status", "--porcelain"):
        raise RuntimeError("tau2 replication requires a clean Git worktree")
    contract = read_json(args.config.resolve())
    source_root = args.source_root.resolve()
    tasks = validate_replication_contract(contract, source_root)
    model_identity, model_manifest = resolve_model_artifact(args.model.resolve())
    user_path = Path(contract["protocol"]["user"]["path"]).resolve()
    user_identity, user_manifest = resolve_model_artifact(user_path)
    expected_user_identity = f"{contract['protocol']['user']['model']}@{contract['protocol']['user']['revision']}"
    if user_identity != expected_user_identity:
        raise RuntimeError("tau2 user-simulator model identity drift")

    tau2_python = absolute_executable(args.tau2_python)
    server_python = absolute_executable(args.server_python)
    for executable in (tau2_python, server_python):
        if not executable.is_file():
            raise RuntimeError(f"required Python environment is missing: {executable}")
    if args.agent_gpu == args.user_gpu:
        raise ValueError("tau2 replication requires separate agent and user GPUs")
    if args.agent_port == args.user_port:
        raise ValueError("tau2 replication requires separate local ports")

    environment = local_tau2_environment()
    cli_preflight = [str(tau2_python), "-m", "tau2.cli", "run", "--help"]
    completed = subprocess.run(
        cli_preflight,
        cwd=source_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(f"tau2 CLI preflight failed: {completed.stderr[-1000:]}")

    if args.preflight_only:
        print(
            json.dumps(
                {
                    "schema_version": "studyhub.tau2-replication-preflight.v1",
                    "status": "PASS_TAU2_REPLICATION_PREFLIGHT",
                    "git_commit": git_value("rev-parse", "HEAD"),
                    "config_sha256": sha256(args.config.resolve()),
                    "selection_canonical_sha256": contract["selection"]["canonical_sha256"],
                    "expected_tasks": sum(map(len, tasks.values())),
                    "source_lock": read_json(source_root / ".studyhub-external-lock.json"),
                    "model": model_identity,
                    "model_manifest": model_manifest,
                    "user_simulator": user_identity,
                    "user_manifest": user_manifest,
                    "tau2_python": str(tau2_python),
                    "server_python": str(server_python),
                    "fresh_holdout_used": False,
                    "gpu_started": False,
                    "model_score": "NOT_RUN",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    for gpu in (args.agent_gpu, args.user_gpu):
        if compute_pids(gpu):
            raise RuntimeError(f"GPU {gpu} already has compute processes")

    run_id = args.run_id or f"qwen35-4b-m1-tau2-15-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_root = args.output_root.resolve() / run_id
    if run_root.exists() and any(run_root.iterdir()):
        raise RuntimeError(f"tau2 run directory is not empty: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    protocol = contract["protocol"]
    commands = {
        domain: tau2_command(
            tau2_python=tau2_python,
            domain=domain,
            task_ids=task_ids,
            save_to=run_root / domain,
            agent_port=args.agent_port,
            user_port=args.user_port,
            protocol=protocol,
        )
        for domain, task_ids in tasks.items()
    }
    manifest = {
        "schema_version": "studyhub.tau2-replication-run.v1",
        "status": "RUNNING",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_value("rev-parse", "HEAD"),
        "config_sha256": sha256(args.config.resolve()),
        "selection_canonical_sha256": contract["selection"]["canonical_sha256"],
        "source_lock": read_json(source_root / ".studyhub-external-lock.json"),
        "model": model_identity,
        "model_manifest": model_manifest,
        "user_simulator": user_identity,
        "user_manifest": user_manifest,
        "server_python": str(server_python),
        "tau2_python": str(tau2_python),
        "agent_gpu": args.agent_gpu,
        "user_gpu": args.user_gpu,
        "agent_port": args.agent_port,
        "user_port": args.user_port,
        "commands": commands,
        "claim_boundary": contract["claim_boundary"],
    }
    write_json(run_root / "run-manifest.json", manifest)
    with (run_root / "tau2-environment.txt").open("w", encoding="utf-8") as stream:
        subprocess.run(
            ["uv", "pip", "freeze", "--python", str(tau2_python)],
            check=True,
            stdout=stream,
            text=True,
        )

    processes: list[tuple[subprocess.Popen[str], Any]] = []
    telemetry: list[GpuTelemetry] = []
    started = time.monotonic()
    try:
        agent_server, agent_stream = launch_server(
            python=server_python,
            model=args.model.resolve(),
            gpu=args.agent_gpu,
            port=args.agent_port,
            log_path=run_root / "agent-sglang.log",
            server=contract["servers"],
        )
        user_server, user_stream = launch_server(
            python=server_python,
            model=user_path,
            gpu=args.user_gpu,
            port=args.user_port,
            log_path=run_root / "user-sglang.log",
            server=contract["servers"],
        )
        processes.extend(((agent_server, agent_stream), (user_server, user_stream)))
        agent_telemetry = GpuTelemetry(args.agent_gpu, run_root / "agent-gpu.csv", agent_server.pid)
        user_telemetry = GpuTelemetry(args.user_gpu, run_root / "user-gpu.csv", user_server.pid)
        telemetry.extend((agent_telemetry, user_telemetry))
        for monitor in telemetry:
            monitor.start()
        wait_for_server(f"http://127.0.0.1:{args.agent_port}/v1", agent_server, args.server_timeout, "EMPTY")
        wait_for_server(f"http://127.0.0.1:{args.user_port}/v1", user_server, args.server_timeout, "EMPTY")
        for domain, command in commands.items():
            run_logged(command, cwd=source_root, environment=environment, log_path=run_root / f"{domain}.log")
            foreign = sorted({pid for monitor in telemetry for pid in monitor.foreign_pids})
            if foreign:
                raise RuntimeError(f"foreign GPU processes appeared during tau2 {domain}: {foreign}")
    finally:
        for monitor in telemetry:
            monitor.stop()
        for process, stream in reversed(processes):
            terminate_process_group(process)
            stream.close()

    domains = {
        domain: summarize_domain(run_root / domain / "results.json", task_ids) for domain, task_ids in tasks.items()
    }
    total_tasks = sum(value["tasks"] for value in domains.values())
    reward_sum = sum(value["reward_sum"] for value in domains.values())
    summary = {
        "schema_version": "studyhub.tau2-replication-summary.v1",
        "status": "COMPLETED_TAU2_PUBLIC_PARTIAL_REPLICATION",
        "run_id": run_id,
        "model": model_identity,
        "user_simulator": user_identity,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "scores": {
            "reward_sum": reward_sum,
            "mean_reward": reward_sum / total_tasks,
            "tasks": total_tasks,
            "domains": domains,
            "official_full_leaderboard_score": False,
        },
        "claim_boundary": contract["claim_boundary"],
    }
    write_json(run_root / "summary.json", summary)
    manifest.update(
        {
            "status": summary["status"],
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "summary_sha256": sha256(run_root / "summary.json"),
        }
    )
    write_json(run_root / "run-manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
