import json
import socket
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from studyhub_agent.serving import checks, cli
from studyhub_agent.serving.config import VLLM_VERSION, ServingConfig, command, environment, load_config, model_identity


def config_with(config, **changes):
    return ServingConfig.model_validate(config.model_dump() | changes)


def test_paths_are_relative_to_config_and_venv_symlink_is_preserved(tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    interpreter = tmp_path / "venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to("/usr/bin/python3")
    path = directory / "serve.toml"
    path.write_text('model_dir="../model"\nruntime_python="../venv/bin/python"\nstate_dir="../state"\n')
    config = load_config(path)
    assert config.model_dir == tmp_path / "model"
    assert config.state_dir == tmp_path / "state"
    assert "venv/bin/python" in str(config.runtime_python)
    assert config.runtime_python != interpreter.resolve()


@pytest.mark.parametrize(
    "changes",
    [
        {"host": "0.0.0.0"},
        {"host": "example.com"},
        {"gpus": ["0", "0"], "tensor_parallel_size": 2},
        {"gpus": ["0", "1"]},
        {"gpus": ["MIG-123"]},
        {"max_model_len": 8192},
        {"gpu_memory_utilization": 0.99},
        {"api_key_env": "secret-value"},
        {"served_model_name": "a\nb"},
        {"unknown_option": True},
    ],
)
def test_reject_unsafe_or_incoherent_configuration(serving_config, changes):
    with pytest.raises(ValidationError):
        config_with(serving_config, **changes)


def test_command_defaults_and_optional_features(serving_config, monkeypatch):
    monkeypatch.setenv(serving_config.api_key_env, "fake-test-secret")
    args = command(serving_config)
    for flag, expected in {
        "--tool-call-parser": "qwen3_coder",
        "--reasoning-parser": "qwen3",
        "--max-model-len": "16384",
        "--max-num-seqs": "4",
        "--max-cudagraph-capture-size": "4",
        "--mamba-cache-mode": "none",
        "--generation-config": "vllm",
        "--dtype": "bfloat16",
    }.items():
        assert args[args.index(flag) + 1] == expected
    assert "--language-model-only" in args
    assert "--no-trust-request-chat-template" in args
    assert "--no-enable-prefix-caching" in args
    assert "--api-key" not in args and "fake-test-secret" not in repr(args)
    assert "--trust-remote-code" not in args and "--speculative-config" not in args
    optional = command(config_with(serving_config, prefix_caching=True, enforce_eager=True))
    assert "--enable-prefix-caching" in optional and "--enforce-eager" in optional
    assert "--max-cudagraph-capture-size" not in optional
    assert optional[optional.index("--mamba-cache-mode") + 1] == "align"
    assert config_with(serving_config, host="::1").base_url == "http://[::1]:30411"


def test_environment_offline_auth_and_physical_devices(serving_config, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/legacy/sglang/patches")
    monkeypatch.setenv("STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC", "1")
    monkeypatch.setenv("VLLM_API_KEY", "unrelated-secret")
    monkeypatch.delenv(serving_config.api_key_env, raising=False)
    assert "VLLM_API_KEY" not in environment(serving_config)
    monkeypatch.setenv(serving_config.api_key_env, "fake-secret")
    env = environment(serving_config, gpu_uuids=["GPU-123"])
    assert env["VLLM_API_KEY"] == "fake-secret"
    assert env["CUDA_VISIBLE_DEVICES"] == "GPU-123"
    assert env["HF_HUB_OFFLINE"] == "1" and env["VLLM_USE_RUST_FRONTEND"] == "0"
    assert env["NO_PROXY"] == env["no_proxy"]
    assert "PYTHONPATH" not in env and "STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC" not in env
    assert not serving_config.state_dir.exists()


def test_model_manifest_and_template_pin(serving_config):
    identity = model_identity(serving_config)
    assert len(identity["sha256"]) == 5
    assert identity["shards"]["model.safetensors"] > 0
    assert not identity["weight_hash_verified"]
    (serving_config.model_dir / "chat_template.jinja").write_text("wrong-template")
    with pytest.raises(ValueError, match="模板"):
        model_identity(serving_config)


@pytest.mark.parametrize(
    "mutation",
    [
        "architecture",
        "context",
        "empty",
        "missing",
        "traversal",
        "bad-map",
        "metadata-list",
        "text-config",
        "index-list",
    ],
)
def test_model_files_rejected(serving_config, mutation):
    model = serving_config.model_dir
    if mutation in {"architecture", "context", "metadata-list", "text-config"}:
        metadata = json.loads((model / "config.json").read_text())
        if mutation == "architecture":
            metadata["model_type"] = "other"
        elif mutation == "context":
            metadata["text_config"]["max_position_embeddings"] = 8192
        elif mutation == "metadata-list":
            metadata = []
        else:
            metadata["text_config"] = None
        (model / "config.json").write_text(json.dumps(metadata))
    elif mutation == "empty":
        (model / "model.safetensors").write_bytes(b"")
    elif mutation == "missing":
        (model / "model.safetensors").unlink()
    elif mutation == "index-list":
        (model / "model.safetensors.index.json").write_text("[]")
    else:
        (model / "model.safetensors.index.json").write_text(
            json.dumps(
                {
                    "weight_map": {"x": "../other.safetensors"} if mutation == "traversal" else [],
                }
            )
        )
    with pytest.raises(ValueError):
        model_identity(serving_config)


def test_gpu_snapshot_parsing(monkeypatch):
    results = iter(
        [
            SimpleNamespace(stdout="0, GPU-abcd, NVIDIA H100, 580.99, 80000, 60000, 5\n"),
            SimpleNamespace(stdout="GPU-abcd, 123\nGPU-other, 456\n"),
        ]
    )
    monkeypatch.setattr(checks.subprocess, "run", lambda *a, **kw: next(results))
    assert checks.gpu_snapshot()[0]["pids"] == [123]


def test_physical_gpu_aliases_and_missing_gpu(serving_config, gpu):
    assert checks.select_gpus(serving_config, [gpu]) == [gpu]
    with pytest.raises(ValueError, match="找不到"):
        checks.select_gpus(config_with(serving_config, gpus=["1"]), [gpu])
    with pytest.raises(ValueError, match="同一张"):
        checks.select_gpus(config_with(serving_config, gpus=["0", gpu["uuid"]], tensor_parallel_size=2), [gpu])


def test_busy_gpu_memory_reserve_and_driver_warning(serving_config, gpu, monkeypatch):
    monkeypatch.setattr(checks, "gpu_snapshot", lambda: [gpu | {"pids": [123], "free_mib": 1000, "driver": "535.99"}])
    monkeypatch.setattr(checks, "port_available", lambda _: True)
    report = checks.preflight(serving_config, inspect_runtime=False)
    assert {row["code"] for row in report["issues"]} == {"gpu_busy", "gpu_memory"}
    assert not report["ok"] and "CUDA 13" in report["warnings"][0]
    report = checks.preflight(
        config_with(serving_config, allow_shared_gpu=True, prefix_caching=True), inspect_runtime=False
    )
    assert "gpu_busy" not in {row["code"] for row in report["issues"]}
    assert len(report["warnings"]) == 3


def test_preflight_runtime_versions_and_flags(serving_config, gpu, monkeypatch):
    monkeypatch.setattr(checks, "gpu_snapshot", lambda: [gpu])
    monkeypatch.setattr(checks, "port_available", lambda _: True)

    def run(args, **kwargs):
        if "-c" in args:
            return SimpleNamespace(
                stdout=json.dumps({"vllm": VLLM_VERSION, "torch": "2.13.0", "transformers": "5.18.0"})
            )
        return SimpleNamespace(stdout=" ".join(command(serving_config)), returncode=0)

    monkeypatch.setattr(checks.subprocess, "run", run)
    assert checks.preflight(serving_config)["ok"]
    results = iter([SimpleNamespace(stdout='{"vllm":"old"}'), SimpleNamespace(stdout="", returncode=1)])
    monkeypatch.setattr(checks.subprocess, "run", lambda *a, **kw: next(results))
    assert {row["code"] for row in checks.preflight(serving_config)["issues"]} == {"runtime_version", "runtime_flags"}


def test_preflight_collects_failures(serving_config, monkeypatch):
    (serving_config.model_dir / "config.json").unlink()

    def failure(*a, **kw):
        raise FileNotFoundError("test")

    monkeypatch.setattr(checks, "gpu_snapshot", failure)
    monkeypatch.setattr(checks, "port_available", lambda _: False)
    monkeypatch.setattr(checks.subprocess, "run", failure)
    assert {row["code"] for row in checks.preflight(serving_config)["issues"]} == {
        "model_files",
        "gpu_inspection",
        "port_busy",
        "runtime_unavailable",
    }


def test_weight_budget_floor(serving_config, gpu, monkeypatch):
    monkeypatch.setattr(checks, "model_identity", lambda _: {"shards": {"big": 50 * 1024**3}})
    monkeypatch.setattr(checks, "gpu_snapshot", lambda: [gpu])
    monkeypatch.setattr(checks, "port_available", lambda _: True)
    assert checks.preflight(serving_config, inspect_runtime=False)["issues"][0]["code"] == "weight_budget"


def test_port_collision(serving_config):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert not checks.port_available(config_with(serving_config, port=port))


def test_cli_plan_has_no_side_effects_and_sanitizes_errors(serving_config, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda _: serving_config)
    monkeypatch.setenv(serving_config.api_key_env, "fake-secret-never-print")
    assert cli.main(["plan", "--config", "ignored.toml"]) == 0
    output = capsys.readouterr().out
    assert "fake-secret-never-print" not in output and not serving_config.state_dir.exists()
    assert json.loads(output)["required_vllm"] == VLLM_VERSION
    monkeypatch.setattr(cli, "preflight", lambda _: {"ok": False})
    assert cli.main(["check", "--config", "ignored"]) == 2
    monkeypatch.setattr(cli, "smoke", lambda _: {"ok": True})
    assert cli.main(["probe", "--config", "ignored"]) == 0
    monkeypatch.setattr(cli, "supervise", lambda _: {"status": "stopped"})
    assert cli.main(["run", "--config", "ignored"]) == 0

    # An upstream client exception must not echo request bodies or keys.
    from studyhub_agent.runtime.policy import PolicyInfraError

    def policy_failure(_):
        raise PolicyInfraError("fake-secret-never-print")

    monkeypatch.setattr(cli, "smoke", policy_failure)
    assert cli.main(["probe", "--config", "ignored"]) == 2
    assert "fake-secret-never-print" not in capsys.readouterr().err
