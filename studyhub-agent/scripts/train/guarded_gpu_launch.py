#!/usr/bin/env python3
"""Launch one training group with exclusive or explicitly budgeted shared GPUs."""

from __future__ import annotations

import argparse
import csv
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


class WallTimeExceeded(RuntimeError):
    """Raised when the explicitly authorized launcher wall time expires."""


def nvidia_query(gpus: str, query: str) -> list[list[str]]:
    output = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            gpus,
            f"--query-gpu={query}",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [[cell.strip() for cell in line.split(",")] for line in output.splitlines() if line.strip()]


def compute_pids(gpu: str) -> list[int]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            gpu,
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    pids = []
    for value in result.stdout.splitlines():
        value = value.strip()
        if value.isdigit():
            pids.append(int(value))
    return pids


def process_group(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except ProcessLookupError:
        return None


def memory_ownership(gpu: str, own_pgid: int) -> dict:
    result = subprocess.run(
        ["nvidia-smi", "-i", gpu, "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    own_mib, foreign_mib, foreign_pids = 0, 0, []
    for row in result.stdout.splitlines():
        if not row.strip():
            continue
        values = [part.strip() for part in row.split(",")]
        if len(values) != 2 or not all(value.isdigit() for value in values):
            raise RuntimeError(f"GPU {gpu}: process memory accounting unavailable")
        pid, memory = map(int, values)
        if process_group(pid) == own_pgid:
            own_mib += memory
        else:
            foreign_mib += memory
            foreign_pids.append(pid)
    return {"own_mib": own_mib, "foreign_mib": foreign_mib, "foreign_pids": foreign_pids}


def validate_resource_sample(
    *,
    gpu: str,
    used_mib: int,
    free_mib: int,
    ownership: dict,
    allow_shared: bool,
    max_used_mib: int,
    max_own_used_mib: int | None,
    min_runtime_free_mib: int,
) -> None:
    if used_mib > max_used_mib:
        raise RuntimeError(f"GPU {gpu} reached {used_mib} MiB; total guard is {max_used_mib} MiB")
    if allow_shared:
        if max_own_used_mib is None or ownership["own_mib"] > max_own_used_mib:
            raise RuntimeError(f"GPU {gpu}: own memory {ownership['own_mib']} MiB exceeds guard {max_own_used_mib}")
        if free_mib < min_runtime_free_mib:
            raise RuntimeError(f"GPU {gpu}: free memory {free_mib} MiB below shared reserve {min_runtime_free_mib}")
    elif ownership["foreign_pids"]:
        raise RuntimeError(f"unrelated compute processes appeared on GPU {gpu}: {ownership['foreign_pids']}")


def process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_group(process: subprocess.Popen[str]) -> None:
    pgid = process.pid
    if not process_group_exists(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + 8
    while process_group_exists(pgid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if process_group_exists(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def interrupt_group(process: subprocess.Popen[str], grace_seconds: int) -> None:
    """Give the child a chance to leave a consistent recovery checkpoint."""
    pgid = process.pid
    if not process_group_exists(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGINT)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while process_group_exists(pgid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if process_group_exists(pgid):
        terminate_group(process)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpus", required=True)
    parser.add_argument("--min-free-mib", type=int, required=True)
    parser.add_argument("--max-used-mib", type=int, required=True)
    parser.add_argument("--allow-shared-gpu", action="store_true")
    parser.add_argument("--max-own-used-mib", type=int)
    parser.add_argument("--min-runtime-free-mib", type=int, default=0)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--gpu-csv", type=Path, required=True)
    parser.add_argument("--max-wall-seconds", type=int)
    parser.add_argument("--interrupt-grace-seconds", type=int, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gpus = [value.strip() for value in args.gpus.split(",") if value.strip()]
    if not gpus or len(gpus) != len(set(gpus)):
        raise ValueError("--gpus must contain unique comma-separated GPU indices")
    if not args.command:
        raise ValueError("missing command")
    if args.max_wall_seconds is not None and args.max_wall_seconds < 1:
        raise ValueError("--max-wall-seconds must be positive")
    if args.interrupt_grace_seconds < 1:
        raise ValueError("--interrupt-grace-seconds must be positive")
    if args.allow_shared_gpu and (
        args.max_own_used_mib is None
        or args.max_own_used_mib <= 0
        or args.min_runtime_free_mib <= 0
        or args.min_free_mib < args.max_own_used_mib + args.min_runtime_free_mib
    ):
        raise ValueError("shared GPUs require an explicit own-memory cap and reserved headroom at admission")
    command = args.command[1:] if args.command[0] == "--" else args.command

    initial = nvidia_query(",".join(gpus), "index,memory.free")
    if len(initial) != len(gpus):
        raise RuntimeError(f"could not query every requested GPU: {gpus}")
    for gpu, free in initial:
        if int(free) < args.min_free_mib:
            raise RuntimeError(f"GPU {gpu} has {free} MiB free; require {args.min_free_mib} MiB")
        pids = compute_pids(gpu)
        if pids and not args.allow_shared_gpu:
            raise RuntimeError(f"GPU {gpu} already has compute processes: {pids}")

    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.gpu_csv.parent.mkdir(parents=True, exist_ok=True)
    with (
        args.log.open("w", encoding="utf-8") as log_stream,
        args.gpu_csv.open("w", encoding="utf-8", newline="") as csv_stream,
    ):
        writer = csv.writer(csv_stream)
        writer.writerow(
            [
                "timestamp",
                "index",
                "memory_used_mib",
                "memory_free_mib",
                "utilization_gpu_pct",
                "power_w",
                "own_memory_used_mib",
                "foreign_memory_used_mib",
                "foreign_process_count",
            ]
        )
        csv_stream.flush()
        process = subprocess.Popen(
            command,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        started = time.monotonic()
        print(f"Training PID {process.pid}; log {args.log}", flush=True)
        try:
            while process.poll() is None:
                if args.max_wall_seconds is not None and time.monotonic() - started >= args.max_wall_seconds:
                    raise WallTimeExceeded(f"authorized wall time reached: {args.max_wall_seconds}s")
                samples = nvidia_query(
                    ",".join(gpus),
                    "index,memory.used,memory.free,utilization.gpu,power.draw",
                )
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                if len(samples) != len(gpus) or any(len(sample) != 5 for sample in samples):
                    raise RuntimeError("GPU telemetry became incomplete")
                for sample in samples:
                    gpu = sample[0]
                    ownership = (
                        memory_ownership(gpu, process.pid)
                        if args.allow_shared_gpu
                        else {
                            "own_mib": None,
                            "foreign_mib": None,
                            "foreign_pids": [
                                pid for pid in compute_pids(gpu) if process_group(pid) not in (None, process.pid)
                            ],
                        }
                    )
                    writer.writerow(
                        [
                            timestamp,
                            *sample,
                            ownership["own_mib"],
                            ownership["foreign_mib"],
                            len(ownership["foreign_pids"]),
                        ]
                    )
                    csv_stream.flush()
                    validate_resource_sample(
                        gpu=gpu,
                        used_mib=int(sample[1]),
                        free_mib=int(sample[2]),
                        ownership=ownership,
                        allow_shared=args.allow_shared_gpu,
                        max_used_mib=args.max_used_mib,
                        max_own_used_mib=args.max_own_used_mib,
                        min_runtime_free_mib=args.min_runtime_free_mib,
                    )
                time.sleep(5)
        except (KeyboardInterrupt, RuntimeError, subprocess.SubprocessError, OSError, ValueError) as exc:
            print(f"GPU guard stopped only process group {process.pid}: {exc}", file=sys.stderr)
            if isinstance(exc, (KeyboardInterrupt, WallTimeExceeded)):
                interrupt_group(process, args.interrupt_grace_seconds)
            else:
                terminate_group(process)
            if isinstance(exc, KeyboardInterrupt):
                return 130
            if isinstance(exc, WallTimeExceeded):
                return 124
            return 70
        status = process.wait()
        terminate_group(process)
        return status


if __name__ == "__main__":
    raise SystemExit(main())
