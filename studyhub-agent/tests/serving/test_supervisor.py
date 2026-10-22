import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from unittest.mock import Mock

import httpx
import pytest

from studyhub_agent.serving import supervisor


def manifest(config):
    return json.loads(next(config.state_dir.glob("*/run.json")).read_text())


def prepare(config, gpu, monkeypatch):
    monkeypatch.setattr(supervisor, "gpu_snapshot", lambda: [gpu])
    monkeypatch.setattr(supervisor, "preflight", lambda _: {"ok": True, "gpus": [gpu]})
    # Real subprocess and real process group; no vLLM or GPU allocation in these tests.
    monkeypatch.setattr(
        supervisor,
        "command",
        lambda _: [
            sys.executable,
            "-c",
            "import os,time; print(os.getenv('VLLM_API_KEY','ready'),flush=True); time.sleep(60)",
        ],
    )


def assert_stopped_own_child(data):
    with pytest.raises(ProcessLookupError):
        os.kill(data["pid"], 0)


def test_signal_shutdown_redaction_and_signal_handler_restore(serving_config, gpu, monkeypatch):
    prepare(serving_config, gpu, monkeypatch)
    previous = signal.getsignal(signal.SIGTERM)
    monkeypatch.setenv(serving_config.api_key_env, "fake-private-key")

    def ready(client, config):
        assert client.headers["Authorization"] == "Bearer fake-private-key"
        log_path = next(config.state_dir.glob("*/server.log"))
        deadline = time.monotonic() + 3
        while "[REDACTED]" not in log_path.read_text():
            assert time.monotonic() < deadline, "child log was not drained and redacted"
            time.sleep(0.01)
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(supervisor, "check_identity", ready)
    report = supervisor.supervise(serving_config)
    assert report["status"] == "stopped" and report["events"][0]["event"] == "ready"
    assert signal.getsignal(signal.SIGTERM) == previous
    assert_stopped_own_child(report)
    assert "fake-private-key" not in json.dumps(report)
    log = next(serving_config.state_dir.glob("*/server.log")).read_text()
    assert "fake-private-key" not in log and "[REDACTED]" in log


def test_readiness_over_real_loopback_http(serving_config, gpu, monkeypatch):
    prepare(serving_config, gpu, monkeypatch)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = serving_config.model_copy(update={"port": port, "poll_interval_s": 0.1})
    script = """
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        if self.path == '/v1/models':
            self.wfile.write(json.dumps({'data':[{'id':'Qwen/Qwen3.5-9B','max_model_len':16384}]}).encode())
HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
""".replace("PORT", str(port))
    monkeypatch.setattr(supervisor, "command", lambda _: [sys.executable, "-c", script])
    original = supervisor.check_identity

    def ready(client, config):
        original(client, config)
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(supervisor, "check_identity", ready)
    report = supervisor.supervise(config)
    assert report["status"] == "stopped" and report["events"][0]["event"] == "ready"
    assert_stopped_own_child(report)


@pytest.mark.parametrize("failure", ["reserve", "foreign-pid", "gpu-monitor", "early-exit", "timeout", "reader"])
def test_failure_cleans_real_child(serving_config, gpu, monkeypatch, failure):
    prepare(serving_config, gpu, monkeypatch)
    config = serving_config.model_copy(update={"poll_interval_s": 0.1, "startup_timeout_s": 1})
    monkeypatch.setattr(supervisor, "check_identity", lambda *a: None)
    expected = {
        "reserve": "gpu_reserve_exhausted",
        "foreign-pid": "other_gpu_process_appeared",
        "gpu-monitor": "gpu_monitor_failed",
        "early-exit": "model_process_exited",
        "timeout": "startup_timeout",
    }
    if failure == "reserve":
        gpu["free_mib"] = 10
    if failure == "foreign-pid":
        gpu["pids"] = [os.getpid()]
    if failure == "gpu-monitor":
        rows = iter([[gpu]])

        def snapshot():
            try:
                return next(rows)
            except StopIteration:
                raise OSError("test") from None

        monkeypatch.setattr(supervisor, "gpu_snapshot", snapshot)
    if failure in {"timeout", "early-exit"}:

        def not_ready(*a):
            raise httpx.ConnectError("not ready")

        monkeypatch.setattr(supervisor, "check_identity", not_ready)
    if failure == "early-exit":
        monkeypatch.setattr(supervisor, "command", lambda _: [sys.executable, "-c", "raise SystemExit(7)"])
    if failure == "reader":

        def fail_start(_):
            raise RuntimeError("thread start failed")

        monkeypatch.setattr(supervisor.threading.Thread, "start", fail_start)
    error_type = RuntimeError if failure == "reader" else supervisor.ServingError
    with pytest.raises(error_type, match="thread start" if failure == "reader" else expected[failure]):
        supervisor.supervise(config)
    data = manifest(config)
    assert data["status"] == "failed" and "ended_utc" in data
    assert_stopped_own_child(data)


def test_preflight_refusal_and_lock_contention(serving_config, gpu, monkeypatch):
    prepare(serving_config, gpu, monkeypatch)
    monkeypatch.setattr(supervisor, "preflight", lambda _: {"ok": False, "issues": ["gpu_busy"]})
    with pytest.raises(supervisor.ServingError, match="gpu_busy"):
        supervisor.supervise(serving_config)
    assert not list(serving_config.state_dir.glob("*/run.json"))
    with (serving_config.state_dir / f"gpu-{gpu['uuid']}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(supervisor.ServingError, match="lock_busy"):
            supervisor.supervise(serving_config)


def test_spawn_failure_is_recorded(serving_config, gpu, monkeypatch):
    prepare(serving_config, gpu, monkeypatch)
    monkeypatch.setattr(supervisor, "command", lambda _: ["/nonexistent/python"])
    with pytest.raises(FileNotFoundError):
        supervisor.supervise(serving_config)
    data = manifest(serving_config)
    assert data["status"] == "failed" and data["exit_code"] is None


def test_initial_gpu_inspection_failure(serving_config, monkeypatch):
    def fail():
        raise OSError("test")

    monkeypatch.setattr(supervisor, "gpu_snapshot", fail)
    with pytest.raises(supervisor.ServingError, match="gpu_inspection_failed"):
        supervisor.supervise(serving_config)


def test_force_kill_only_owned_process_group(monkeypatch):
    process = Mock(pid=999999)
    process.wait.side_effect = [subprocess.TimeoutExpired("child", 1), 0]
    kill = Mock()
    monkeypatch.setattr(supervisor.os, "killpg", kill)
    supervisor.stop_child(process, 1)
    assert kill.call_args_list[0].args == (999999, signal.SIGTERM)
    assert kill.call_args_list[1].args == (999999, signal.SIGKILL)
    kill.side_effect = ProcessLookupError
    supervisor.stop_child(process, 1)
