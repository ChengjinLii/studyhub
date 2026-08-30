from __future__ import annotations

import json
from pathlib import Path

from external_benchmarks.adapters.bfcl_prompt import disable_thinking_generation_prefix
from scripts.benchmark.external.run_bfcl_replication import (
    bfcl_commands,
    collect_score_summary,
    temporary_test_ids,
    validate_replication_contract,
)

PROJECT = Path(__file__).resolve().parents[3]


def _source(tmp_path: Path, contract: dict) -> Path:
    source = tmp_path / "source"
    (source / "berkeley-function-call-leaderboard/bfcl_eval/eval_checker").mkdir(parents=True)
    (source / "berkeley-function-call-leaderboard/bfcl_eval/eval_checker/eval_runner.py").write_text("# pinned\n")
    (source / ".studyhub-external-lock.json").write_text(
        json.dumps(
            {
                "resolved_commit": contract["benchmark"]["resolved_commit"],
                "tree": contract["benchmark"]["git_tree"],
            }
        )
    )
    return source


def test_frozen_replication_contract_has_exact_public_70_case_panel(tmp_path: Path) -> None:
    contract = json.loads((PROJECT / "configs/eval/qwen35-4b-bfcl-replication-v1.json").read_text(encoding="utf-8"))
    cases = validate_replication_contract(contract, _source(tmp_path, contract))
    assert sum(map(len, cases.values())) == 70
    assert set(cases) == {
        "simple_python",
        "parallel",
        "multiple",
        "irrelevance",
        "multi_turn_base",
        "multi_turn_miss_func",
        "multi_turn_miss_param",
    }
    assert contract["claim_boundary"] == {
        "official_full_leaderboard_score": False,
        "public_partial_replication_only": True,
        "fresh_holdout_used": False,
        "training_or_tuning_input": False,
    }


def test_temporary_run_ids_restore_prior_file(tmp_path: Path) -> None:
    path = tmp_path / "test_case_ids_to_generate.json"
    path.write_text('{"prior": ["prior_1"]}\n', encoding="utf-8")
    with temporary_test_ids(tmp_path, {"simple_python": ["simple_python_1"]}) as installed:
        assert json.loads(installed.read_text()) == {"simple_python": ["simple_python_1"]}
    assert path.read_text(encoding="utf-8") == '{"prior": ["prior_1"]}\n'


def test_official_commands_use_run_ids_and_partial_eval(tmp_path: Path) -> None:
    generate, evaluate = bfcl_commands(
        python=tmp_path / "python",
        entrypoint=tmp_path / "entrypoint.py",
        registry_name="StudyHub/M1",
        model=tmp_path / "model",
        result_dir=tmp_path / "result",
        score_dir=tmp_path / "score",
        temperature=0.001,
        num_threads=4,
    )
    assert "--run-ids" in generate
    assert "--skip-server-setup" in generate
    assert "--partial-eval" in evaluate
    assert all("holdout" not in value for value in generate + evaluate)


def test_bfcl_qwen_adapter_disables_thinking_at_generation_boundary() -> None:
    prompt = disable_thinking_generation_prefix("prefix<|im_start|>assistant\n")
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_score_summary_preserves_official_category_counts(tmp_path: Path) -> None:
    score = tmp_path / "score/model/non_live"
    score.mkdir(parents=True)
    (score / "BFCL_v4_simple_python_score.json").write_text(
        '{"accuracy": 0.9, "correct_count": 9, "total_count": 10}\n{"id":"one"}\n'
    )
    other = tmp_path / "score/model/multi_turn"
    other.mkdir(parents=True)
    (other / "BFCL_v4_multi_turn_base_score.json").write_text(
        '{"accuracy": 0.4, "correct_count": 4, "total_count": 10}\n'
    )
    summary = collect_score_summary(tmp_path / "score", 20)
    assert summary["correct_count"] == 13
    assert summary["total_count"] == 20
    assert summary["selected_case_accuracy"] == 0.65
    assert summary["official_full_leaderboard_score"] is False
