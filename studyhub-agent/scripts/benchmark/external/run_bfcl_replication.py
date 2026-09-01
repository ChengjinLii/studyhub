#!/usr/bin/env python3
"""Run the frozen public BFCL 70-case replication with the official evaluator."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.benchmark.run_9b_base_eval import resolve_model_artifact, wait_for_server

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = Path(
    "/data/chengjin/studyhub/studyhub-agent/artifacts/external-benchmarks/sources/bfcl/"
    "f7cf7359b7ac615a0b294831c5ba2bc95ee4a000"
)
DEFAULT_OUTPUT_ROOT = Path("/data/chengjin/studyhub/studyhub-agent/artifacts/external-benchmarks/runs")
DEFAULT_SERVER_PYTHON = Path("/data/chengjin/studyhub/studyhub-agent/.venv-train/bin/python")
PROXY_ENVIRONMENT_KEYS = (
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


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def absolute_executable(path: Path) -> Path:
    """Keep a venv interpreter path intact instead of resolving its symlink."""

    return Path(os.path.abspath(path.expanduser()))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def git_value(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT.parent,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def local_bfcl_environment() -> dict[str, str]:
    """Build an environment that cannot proxy localhost benchmark traffic."""

    environment = os.environ.copy()
    for key in PROXY_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    return environment


def validate_replication_contract(
    contract: dict[str, Any],
    source_root: Path,
) -> dict[str, list[str]]:
    if contract.get("status") != "FROZEN_BEFORE_M1_COMPLETION":
        raise RuntimeError("BFCL replication selection is not frozen before M1 completion")
    boundary = contract.get("claim_boundary", {})
    if boundary.get("fresh_holdout_used") is not False or boundary.get("training_or_tuning_input") is not False:
        raise RuntimeError("BFCL replication claim boundary permits holdout or training use")

    selection = contract.get("selection", {})
    cases = selection.get("cases")
    if not isinstance(cases, dict) or not cases:
        raise RuntimeError("BFCL replication selection has no cases")
    normalized: dict[str, list[str]] = {}
    flattened: list[str] = []
    for category, values in cases.items():
        if not isinstance(category, str) or not isinstance(values, list) or not values:
            raise RuntimeError("BFCL categories must contain non-empty ID lists")
        ids = [str(value) for value in values]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"BFCL category contains duplicate IDs: {category}")
        if any(not value.startswith(f"{category}_") for value in ids):
            raise RuntimeError(f"BFCL ID/category mismatch: {category}")
        normalized[category] = ids
        flattened.extend(ids)
    if len(flattened) != int(selection["expected_cases"]) or len(flattened) != len(set(flattened)):
        raise RuntimeError("BFCL replication case count or global uniqueness drift")
    if canonical_sha256(normalized) != selection["canonical_sha256"]:
        raise RuntimeError("BFCL replication ID hash drift")
    if contract.get("generation", {}).get("enable_thinking") is not False:
        raise RuntimeError("BFCL replication must keep student thinking disabled")

    marker = read_json(source_root / ".studyhub-external-lock.json")
    benchmark = contract["benchmark"]
    if marker.get("resolved_commit") != benchmark["resolved_commit"] or marker.get("tree") != benchmark["git_tree"]:
        raise RuntimeError("BFCL source revision drift")
    bfcl_root = source_root / "berkeley-function-call-leaderboard"
    if not (bfcl_root / "bfcl_eval/eval_checker/eval_runner.py").is_file():
        raise RuntimeError(f"BFCL official evaluator is missing: {bfcl_root}")
    return normalized


@contextmanager
def temporary_test_ids(bfcl_root: Path, cases: dict[str, list[str]]) -> Iterator[Path]:
    """Install the upstream run-IDs file under an exclusive lock and restore it."""

    lock_path = bfcl_root / ".studyhub-bfcl-run-ids.lock"
    ids_path = bfcl_root / "test_case_ids_to_generate.json"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        previous = ids_path.read_bytes() if ids_path.exists() else None
        temporary = ids_path.with_suffix(".json.partial")
        temporary.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, ids_path)
        try:
            yield ids_path
        finally:
            if previous is None:
                ids_path.unlink(missing_ok=True)
            else:
                ids_path.write_bytes(previous)
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


def bfcl_commands(
    *,
    python: Path,
    entrypoint: Path,
    registry_name: str,
    model: Path,
    result_dir: Path,
    score_dir: Path,
    temperature: float,
    num_threads: int,
) -> tuple[list[str], list[str]]:
    generate = [
        str(python),
        str(entrypoint),
        "generate",
        "--model",
        registry_name,
        "--temperature",
        str(temperature),
        "--num-threads",
        str(num_threads),
        "--skip-server-setup",
        "--local-model-path",
        str(model),
        "--result-dir",
        str(result_dir),
        "--run-ids",
    ]
    evaluate = [
        str(python),
        str(entrypoint),
        "evaluate",
        "--model",
        registry_name,
        "--result-dir",
        str(result_dir),
        "--score-dir",
        str(score_dir),
        "--partial-eval",
    ]
    return generate, evaluate


def launch_server(
    *,
    python: Path,
    model: Path,
    gpu: int,
    port: int,
    log_path: Path,
    generation: dict[str, Any],
) -> tuple[subprocess.Popen[str], Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("w", encoding="utf-8")
    environment = local_bfcl_environment()
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
        "--dtype",
        "bfloat16",
        "--context-length",
        str(generation["context_length"]),
        "--mem-fraction-static",
        str(generation["mem_fraction_static"]),
        "--max-running-requests",
        str(generation["max_running_requests"]),
        "--tool-call-parser",
        str(generation["tool_call_parser"]),
        "--reasoning-parser",
        str(generation["reasoning_parser"]),
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


def compute_pids(gpu: int) -> list[int]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            str(gpu),
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(value.strip()) for value in result.stdout.splitlines() if value.strip().isdigit()]


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        process.wait(timeout=10)


class GpuTelemetry:
    def __init__(self, gpu: int, path: Path, owner_pgid: int) -> None:
        self.gpu = gpu
        self.path = path
        self.owner_pgid = owner_pgid
        self.stop_event = threading.Event()
        self.foreign_pids: set[int] = set()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=10)

    def _run(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["timestamp", "index", "memory_used_mib", "memory_free_mib", "utilization_gpu_pct"])
            while not self.stop_event.is_set():
                sample = subprocess.run(
                    [
                        "nvidia-smi",
                        "-i",
                        str(self.gpu),
                        "--query-gpu=index,memory.used,memory.free,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if sample:
                    writer.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), *sample.split(", ")])
                    stream.flush()
                for pid in compute_pids(self.gpu):
                    try:
                        pgid = os.getpgid(pid)
                    except ProcessLookupError:
                        continue
                    if pgid != self.owner_pgid:
                        self.foreign_pids.add(pid)
                self.stop_event.wait(5)


def run_logged(command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path) -> None:
    with log_path.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, text=True)
    if completed.returncode:
        raise RuntimeError(f"official BFCL command failed ({completed.returncode}); see {log_path}")


def collect_score_summary(score_dir: Path, expected_cases: int) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    for path in sorted(score_dir.rglob("BFCL_v4_*_score.json")):
        first = next((line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()), "")
        if not first:
            raise RuntimeError(f"empty BFCL score file: {path}")
        row = json.loads(first)
        category = path.name.removeprefix("BFCL_v4_").removesuffix("_score.json")
        categories[category] = {
            "accuracy": float(row["accuracy"]),
            "correct_count": int(row["correct_count"]),
            "total_count": int(row["total_count"]),
            "sha256": sha256(path),
        }
    total = sum(row["total_count"] for row in categories.values())
    correct = sum(row["correct_count"] for row in categories.values())
    if total != expected_cases:
        raise RuntimeError(f"BFCL scored {total} cases; expected {expected_cases}")
    return {
        "selected_case_accuracy": correct / total,
        "correct_count": correct,
        "total_count": total,
        "categories": categories,
        "official_full_leaderboard_score": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/eval/qwen35-4b-bfcl-replication-v1.json",
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--port", type=int, default=18142)
    parser.add_argument("--server-python", type=Path, default=DEFAULT_SERVER_PYTHON)
    parser.add_argument("--bfcl-python", type=Path)
    parser.add_argument("--server-timeout", type=int, default=1200)
    parser.add_argument("--registry-name", default="StudyHub/Qwen3.5-4B-M1-FC")
    parser.add_argument("--display-name", default="StudyHub Qwen3.5-4B M1 (FC)")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if git_value("status", "--porcelain"):
        raise RuntimeError("BFCL replication requires a clean Git worktree")
    contract = read_json(args.config.resolve())
    source_root = args.source_root.resolve()
    cases = validate_replication_contract(contract, source_root)
    model_identity, model_manifest = resolve_model_artifact(args.model.resolve())
    bfcl_root = source_root / "berkeley-function-call-leaderboard"
    bfcl_python = absolute_executable(args.bfcl_python or (bfcl_root / ".venv/bin/python"))
    server_python = absolute_executable(args.server_python)
    for executable in (server_python, bfcl_python):
        if not executable.is_file():
            raise RuntimeError(f"required Python environment is missing: {executable}")
    registry_name = str(args.registry_name)
    display_name = str(args.display_name)
    if not registry_name.startswith("StudyHub/") or not display_name.startswith("StudyHub "):
        raise ValueError("BFCL model labels must remain in the StudyHub namespace")
    environment = local_bfcl_environment()
    environment.update(
        {
            "PYTHONPATH": str(bfcl_root),
            "STUDYHUB_BFCL_MODEL_PATH": str(args.model.resolve()),
            "STUDYHUB_BFCL_REGISTRY_NAME": registry_name,
            "STUDYHUB_BFCL_DISPLAY_NAME": display_name,
            "LOCAL_SERVER_ENDPOINT": "127.0.0.1",
            "LOCAL_SERVER_PORT": str(args.port),
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    cli_preflight = [
        str(bfcl_python),
        str(PROJECT_ROOT / "scripts/benchmark/external/bfcl_entrypoint.py"),
        "--help",
    ]
    if args.preflight_only:
        completed = subprocess.run(
            cli_preflight,
            cwd=bfcl_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(f"BFCL CLI preflight failed: {completed.stderr[-1000:]}")
        print(
            json.dumps(
                {
                    "schema_version": "studyhub.bfcl-replication-preflight.v1",
                    "status": "PASS_BFCL_REPLICATION_PREFLIGHT",
                    "git_commit": git_value("rev-parse", "HEAD"),
                    "config_sha256": sha256(args.config.resolve()),
                    "selection_canonical_sha256": contract["selection"]["canonical_sha256"],
                    "expected_cases": sum(map(len, cases.values())),
                    "source_lock": read_json(source_root / ".studyhub-external-lock.json"),
                    "model": model_identity,
                    "model_manifest": model_manifest,
                    "bfcl_python": str(bfcl_python),
                    "server_python": str(server_python),
                    "fresh_holdout_used": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if compute_pids(args.gpu):
        raise RuntimeError(f"GPU {args.gpu} already has compute processes")

    run_id = args.run_id or f"qwen35-4b-m1-bfcl70-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_root = args.output_root.resolve() / run_id
    if run_root.exists() and any(run_root.iterdir()):
        raise RuntimeError(f"BFCL run directory is not empty: {run_root}")
    result_dir = run_root / "result"
    score_dir = run_root / "score"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "test_case_ids_to_generate.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    generation = contract["generation"]
    generate_command, evaluate_command = bfcl_commands(
        python=bfcl_python,
        entrypoint=PROJECT_ROOT / "scripts/benchmark/external/bfcl_entrypoint.py",
        registry_name=registry_name,
        model=args.model.resolve(),
        result_dir=result_dir,
        score_dir=score_dir,
        temperature=float(generation["temperature"]),
        num_threads=int(generation["num_threads"]),
    )
    manifest = {
        "schema_version": "studyhub.bfcl-replication-run.v1",
        "status": "RUNNING",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_value("rev-parse", "HEAD"),
        "config_sha256": sha256(args.config.resolve()),
        "selection_canonical_sha256": contract["selection"]["canonical_sha256"],
        "source_lock": read_json(source_root / ".studyhub-external-lock.json"),
        "model": model_identity,
        "model_manifest": model_manifest,
        "server_python": str(server_python),
        "bfcl_python": str(bfcl_python),
        "gpu": args.gpu,
        "port": args.port,
        "generate_command": generate_command,
        "evaluate_command": evaluate_command,
        "claim_boundary": contract["claim_boundary"],
    }
    write_json(run_root / "run-manifest.json", manifest)
    with (run_root / "bfcl-environment.txt").open("w", encoding="utf-8") as stream:
        subprocess.run(
            ["uv", "pip", "freeze", "--python", str(bfcl_python)],
            check=True,
            stdout=stream,
            text=True,
        )
    run_logged(
        cli_preflight,
        cwd=bfcl_root,
        env=environment,
        log_path=run_root / "bfcl-cli-preflight.log",
    )

    server: subprocess.Popen[str] | None = None
    server_stream: Any | None = None
    telemetry: GpuTelemetry | None = None
    started = time.monotonic()
    try:
        server, server_stream = launch_server(
            python=server_python,
            model=args.model.resolve(),
            gpu=args.gpu,
            port=args.port,
            log_path=run_root / "sglang.log",
            generation=generation,
        )
        telemetry = GpuTelemetry(args.gpu, run_root / "gpu.csv", server.pid)
        telemetry.start()
        wait_for_server(f"http://127.0.0.1:{args.port}/v1", server, args.server_timeout, "EMPTY")
        with temporary_test_ids(bfcl_root, cases):
            run_logged(generate_command, cwd=bfcl_root, env=environment, log_path=run_root / "generate.log")
            if telemetry.foreign_pids:
                raise RuntimeError(
                    f"foreign GPU processes appeared during BFCL generation: {sorted(telemetry.foreign_pids)}"
                )
            run_logged(evaluate_command, cwd=bfcl_root, env=environment, log_path=run_root / "evaluate.log")
            if telemetry.foreign_pids:
                raise RuntimeError(
                    f"foreign GPU processes appeared during BFCL evaluation: {sorted(telemetry.foreign_pids)}"
                )
    finally:
        if telemetry is not None:
            telemetry.stop()
        if server is not None:
            terminate_process_group(server)
        if server_stream is not None:
            server_stream.close()

    scores = collect_score_summary(score_dir, int(contract["selection"]["expected_cases"]))
    summary = {
        "schema_version": "studyhub.bfcl-replication-summary.v1",
        "status": "COMPLETED_BFCL_PUBLIC_PARTIAL_REPLICATION",
        "run_id": run_id,
        "model": model_identity,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "scores": scores,
        "result_tree_files": len([path for path in result_dir.rglob("*") if path.is_file()]),
        "score_tree_files": len([path for path in score_dir.rglob("*") if path.is_file()]),
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
