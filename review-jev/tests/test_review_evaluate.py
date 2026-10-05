import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_review_service import FakeBackend

from review_jev.backends import DemoBackend
from review_jev.config import Settings
from review_jev.evaluate import evaluate_file, probability_metrics
from review_jev.service import ReviewService

ROOT = Path(__file__).resolve().parents[1]


def test_probability_metrics():
    metrics = probability_metrics([(0.9, True), (0.8, False), (0.1, False), (0.2, True)], 0.5)
    assert metrics["true_positive"] == metrics["false_positive"] == 1
    assert metrics["true_negative"] == metrics["false_negative"] == 1
    assert metrics["precision"] == metrics["recall"] == 0.5
    assert metrics["brier_score"] == pytest.approx(0.325)
    assert metrics["ece_10_bins"] == pytest.approx(0.45)


def test_demo_is_excluded_from_quality_metrics():
    service = ReviewService(Settings(backend="demo"), DemoBackend())
    report = evaluate_file(service, ROOT / "examples/evaluation.jsonl")
    assert report["total_cases"] == 3
    assert report["eligible_model_cases"] == 0
    assert report["decision_accuracy"] is None
    assert all(item["labeled_checks"] == 0 for item in report["per_rule"].values())


def test_completed_cases_enter_metrics():
    service = ReviewService(Settings(), FakeBackend())
    report = evaluate_file(service, ROOT / "examples/evaluation.jsonl")
    assert report["eligible_model_cases"] == 3
    assert report["per_rule"]["third_party_reproduction"]["labeled_checks"] == 2
    assert report["per_rule"]["third_party_reproduction"]["false_negative"] == 1


def test_invalid_evaluation_cases_do_not_leak_text(tmp_path):
    dataset = tmp_path / "invalid.jsonl"
    dataset.write_text('{"secret":"SECRET-CONTENT"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid evaluation case at line 1") as info:
        evaluate_file(ReviewService(Settings(backend="demo")), dataset)
    assert "SECRET-CONTENT" not in str(info.value)


def test_cli_review_demo():
    response = subprocess.run(
        [
            sys.executable,
            "-m",
            "review_jev.cli",
            "review",
            str(ROOT / "examples/original-notes.json"),
            "--backend",
            "demo",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(response.stdout)
    assert result["status"] == "demo" and result["decision"] == "manual_review"


def test_cli_evaluation_saves_only_aggregate_report(tmp_path):
    output = tmp_path / "metrics.json"
    response = subprocess.run(
        [
            sys.executable,
            "-m",
            "review_jev.cli",
            "evaluate",
            str(ROOT / "examples/evaluation.jsonl"),
            "--backend",
            "demo",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(output.read_text()) == json.loads(response.stdout)
    assert "Scanned pages" not in response.stdout


def test_nonlocal_bind_requires_api_key(monkeypatch):
    monkeypatch.delenv("REVIEW_JEV_API_KEY", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "review_jev.cli", "serve", "--backend", "demo", "--host", "0.0.0.0"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "REVIEW_JEV_API_KEY" in result.stderr
