from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import subprocess
import threading
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from uuid import uuid4

import httpx

from studyhub_agent.serving.checks import gpu_snapshot, preflight, select_gpus
from studyhub_agent.serving.config import ServingConfig, command, environment
from studyhub_agent.serving.probe import check_identity


class ServingError(RuntimeError):
    pass


def stop_child(process, timeout):
    # Only this invocation's new session is signalled; never read an external PID file or pkill.
    for sig, duration in ((signal.SIGTERM, timeout), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=duration)
        except subprocess.TimeoutExpired:
            continue
        if sig == signal.SIGTERM:
            # The parent may have exited before its workers. Clean only its dedicated process group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return


def supervise(config: ServingConfig):
    config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ExitStack() as stack:
        # Shared among this package's launchers; external GPU use is still guarded separately.
        try:
            selected = select_gpus(config, gpu_snapshot())
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ServingError("gpu_inspection_failed") from exc
        for label in sorted([f"port-{config.port}", *[f"gpu-{row['uuid']}" for row in selected]]):
            lock = stack.enter_context((config.state_dir / f"{label}.lock").open("a"))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ServingError("serving_lock_busy") from exc
        report = preflight(config)
        if not report["ok"]:
            raise ServingError(json.dumps(report, ensure_ascii=False))
        run = config.state_dir / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
        run.mkdir(mode=0o700)
        manifest = {
            "status": "starting",
            "command": command(config),
            "config": config.model_dump(mode="json"),
            "checks": report,
            "started_utc": datetime.now(UTC).isoformat(),
            "events": [],
        }

        def record():
            temporary = run / "run.json.tmp"
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(run / "run.json")

        record()
        stopped = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.signal(sig, lambda *_: stopped.set())
            stack.callback(signal.signal, sig, previous)
        logger = logging.Logger(f"studyhub-vllm-{run.name}", level=logging.INFO)
        handler = RotatingFileHandler(run / "server.log", maxBytes=8 * 1024 * 1024, backupCount=3, encoding="utf-8")
        logger.addHandler(handler)
        stack.callback(handler.close)
        child_env = environment(config, gpu_uuids=[row["uuid"] for row in report["gpus"]])
        process, reader = None, None
        try:
            process = subprocess.Popen(
                command(config),
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            manifest["pid"] = process.pid
            record()

            def drain():
                for line in process.stdout:
                    key = child_env.get("VLLM_API_KEY")
                    logger.info(line.rstrip().replace(key, "[REDACTED]") if key else line.rstrip())

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            print(json.dumps({"run_dir": str(run), "pid": process.pid, "status": "starting"}), flush=True)
            deadline = time.monotonic() + config.startup_timeout_s
            headers = {"Authorization": f"Bearer {child_env['VLLM_API_KEY']}"} if "VLLM_API_KEY" in child_env else {}
            with httpx.Client(timeout=2, trust_env=False, headers=headers) as client:
                while not stopped.is_set():
                    if process.poll() is not None:
                        raise ServingError("model_process_exited")
                    if manifest["status"] == "starting":
                        try:
                            check_identity(client, config)
                        except (httpx.HTTPError, ValueError, KeyError, RuntimeError):
                            if time.monotonic() >= deadline:
                                raise ServingError("startup_timeout") from None
                        else:
                            manifest["status"] = "ready"
                            manifest["events"].append({"event": "ready", "utc": datetime.now(UTC).isoformat()})
                            record()
                            print(json.dumps({"status": "ready", "base_url": config.base_url}), flush=True)
                    try:
                        current_gpus = select_gpus(config, gpu_snapshot())
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        raise ServingError("gpu_monitor_failed") from exc
                    for gpu in current_gpus:
                        if gpu["free_mib"] < config.reserve_memory_mib:
                            raise ServingError("gpu_reserve_exhausted")
                        if not config.allow_shared_gpu:
                            for pid in gpu["pids"]:
                                try:
                                    other_group = os.getpgid(pid) != process.pid
                                except ProcessLookupError:
                                    continue
                                if other_group:
                                    raise ServingError("other_gpu_process_appeared")
                    stopped.wait(config.poll_interval_s)
            manifest["status"] = "stopped"
        except BaseException as exc:
            manifest.update(
                status="failed",
                error=type(exc).__name__,
                error_code=str(exc) if isinstance(exc, ServingError) else "supervisor_error",
            )
            raise
        finally:
            if process is not None:
                stop_child(process, config.shutdown_timeout_s)
                if reader is not None and reader.ident is not None:
                    reader.join(timeout=3)
                process.stdout.close()
            manifest.update(exit_code=process.poll() if process else None, ended_utc=datetime.now(UTC).isoformat())
            record()
        return manifest
