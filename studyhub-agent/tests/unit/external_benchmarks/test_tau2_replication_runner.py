from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark.external.run_tau2_replication import (
    llm_arguments,
    local_tau2_environment,
    summarize_domain,
    tau2_command,
    validate_replication_contract,
)

PROJECT = Path(__file__).resolve().parents[3]


def _source(tmp_path: Path, contract: dict) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".studyhub-external-lock.json").write_text(
        json.dumps(
            {
                "resolved_commit": contract["benchmark"]["resolved_commit"],
                "tree": contract["benchmark"]["git_tree"],
            }
        )
    )
    for domain, task_ids in contract["selection"]["tasks"].items():
        path = source / f"data/tau2/domains/{domain}/tasks.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps([{"id": task_id} for task_id in task_ids]))
        contract["selection"]["source_file_sha256"][domain] = _sha256(path)
    return source


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_replication_contract_has_exact_public_15_task_panel(tmp_path: Path) -> None:
    contract = json.loads((PROJECT / "configs/eval/qwen35-4b-tau2-replication-v1.json").read_text())
    tasks = validate_replication_contract(contract, _source(tmp_path, contract))
    assert sum(map(len, tasks.values())) == 15
    assert set(tasks) == {"airline", "retail", "telecom"}
    assert contract["claim_boundary"]["fresh_holdout_used"] is False
    assert contract["claim_boundary"]["training_or_tuning_input"] is False


def test_tau2_command_uses_official_protocol_and_local_endpoints(tmp_path: Path) -> None:
    protocol = {
        "seed": 20260830,
        "num_trials": 1,
        "max_steps": 50,
        "max_errors": 5,
        "max_concurrency": 1,
        "max_retries": 3,
        "retry_delay_seconds": 1.0,
        "simulation_timeout_seconds": 1200,
        "agent": {"temperature": 0.0, "max_tokens": 4096},
        "user": {"temperature": 0.0, "max_tokens": 1024},
    }
    command = tau2_command(
        tau2_python=tmp_path / "python",
        domain="airline",
        task_ids=["0", "1"],
        save_to=tmp_path / "results",
        agent_port=18144,
        user_port=18145,
        protocol=protocol,
    )
    assert "--enforce-communication-protocol" in command
    assert command[command.index("--task-ids") + 1 : command.index("--num-trials")] == ["0", "1"]
    assert "openai/default" in command
    assert all("holdout" not in value for value in command)
    joined = " ".join(command)
    assert "127.0.0.1:18144" in joined
    assert "127.0.0.1:18145" in joined
    assert '"enable_thinking":false' in joined


def test_local_tau2_environment_removes_proxy_inheritance(monkeypatch) -> None:
    for key in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        monkeypatch.setenv(key, "socks5://127.0.0.1:7893")
    environment = local_tau2_environment()
    assert not any(key in environment for key in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"))
    assert environment["NO_PROXY"] == "127.0.0.1,localhost"


def test_llm_arguments_disable_thinking() -> None:
    value = llm_arguments(port=18144, temperature=0.0, max_tokens=4096)
    assert value["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert value["api_base"] == "http://127.0.0.1:18144/v1"


def test_domain_summary_preserves_official_reward_and_terminations(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "simulations": [
                    {
                        "task_id": "0",
                        "reward_info": {"reward": 1.0},
                        "termination_reason": "user_stop",
                        "duration": 2.0,
                    },
                    {
                        "task_id": "1",
                        "reward_info": {"reward": 0.0},
                        "termination_reason": "agent_error",
                        "duration": 4.0,
                    },
                ]
            }
        )
    )
    summary = summarize_domain(path, ["0", "1"])
    assert summary["reward_sum"] == 1.0
    assert summary["mean_reward"] == 0.5
    assert summary["terminations"] == {"agent_error": 1, "user_stop": 1}
    assert summary["mean_duration_seconds"] == 3.0
