#!/usr/bin/env python3
"""Launch one explicit training command while yielding to every unrelated GPU job."""

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


def terminate_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpus", required=True)
    parser.add_argument("--min-free-mib", type=int, required=True)
    parser.add_argument("--max-used-mib", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--gpu-csv", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gpus = [value.strip() for value in args.gpus.split(",") if value.strip()]
    if not gpus or len(gpus) != len(set(gpus)):
        raise ValueError("--gpus must contain unique comma-separated GPU indices")
    if not args.command:
        raise ValueError("missing command")
    command = args.command[1:] if args.command[0] == "--" else args.command

    initial = nvidia_query(",".join(gpus), "index,memory.free")
    if len(initial) != len(gpus):
        raise RuntimeError(f"could not query every requested GPU: {gpus}")
    for gpu, free in initial:
        if int(free) < args.min_free_mib:
            raise RuntimeError(f"GPU {gpu} has {free} MiB free; require {args.min_free_mib} MiB")
        pids = compute_pids(gpu)
        if pids:
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
        print(f"Training PID {process.pid}; log {args.log}", flush=True)
        try:
            while process.poll() is None:
                samples = nvidia_query(
                    ",".join(gpus),
                    "index,memory.used,memory.free,utilization.gpu,power.draw",
                )
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                for sample in samples:
                    writer.writerow([timestamp, *sample])
                    if int(sample[1]) > args.max_used_mib:
                        raise RuntimeError(f"GPU {sample[0]} reached {sample[1]} MiB; guard is {args.max_used_mib} MiB")
                csv_stream.flush()
                for gpu in gpus:
                    unrelated = [pid for pid in compute_pids(gpu) if process_group(pid) not in (None, process.pid)]
                    if unrelated:
                        raise RuntimeError(f"unrelated compute processes appeared on GPU {gpu}: {unrelated}")
                time.sleep(5)
        except (KeyboardInterrupt, RuntimeError) as exc:
            print(f"GPU guard stopped only process group {process.pid}: {exc}", file=sys.stderr)
            terminate_group(process)
            return 130 if isinstance(exc, KeyboardInterrupt) else 70
        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
