import json
import math
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_review_guard import text_score
from test_review_service import image_uri

from review_jev.config import Settings
from review_jev.ocr import TesseractOCR, parse_tsv
from review_jev.scoring import Calibration, softmax

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tconf\ttext\n"


def test_stable_candidate_softmax():
    assert softmax({"a": -10000, "b": -10000}) == {"a": 0.5, "b": 0.5}
    assert softmax({"a": 2, "b": 0}, 2)["a"] < softmax({"a": 2, "b": 0})["a"]


@pytest.mark.parametrize("temperature", [0, -1, math.nan, math.inf, True, 11])
def test_invalid_temperature(temperature):
    with pytest.raises(ValueError):
        softmax({"a": 1}, temperature)


def test_calibration_requires_matching_model_revision_and_policy(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "model": text_score().model,
                        "model_revision": "pinned",
                        "policy_id": "text_safety",
                        "calibration_id": "validation-1",
                        "dataset_id": "synthetic-test",
                        "temperature": 2,
                    }
                ],
            }
        )
    )
    calibration = Calibration.load(str(path))
    score = text_score()
    assert calibration.apply(score) == score
    score.model_revision = "pinned"
    result = calibration.apply(score)
    assert result.calibrated and result.calibration_id == "validation-1"
    assert result.probabilities == score.probabilities
    assert result.calibrated_probabilities["Safe"] < result.probabilities["Safe"]


def test_changing_temperature_alone_does_not_claim_calibration():
    score = text_score()
    score.temperature = 2
    assert not score.calibrated and score.calibration_id is None


def test_duplicate_calibration_entries_rejected():
    entry = {
        "model": "m",
        "model_revision": "v",
        "policy_id": "text_safety",
        "calibration_id": "id",
        "dataset_id": "dataset",
        "temperature": 1,
    }
    with pytest.raises(ValidationError):
        Calibration.model_validate({"entries": [entry, entry]})


def test_ocr_preserves_lines_and_uses_lowest_word_confidence():
    output = HEADER + "5\t1\t1\t1\t1\t1\t98\tHello\n"
    output += "5\t1\t1\t1\t1\t2\t90\tworld\n5\t1\t1\t1\t2\t1\t20\tRisk\n"
    result = parse_tsv("photo", output, Settings())
    assert result.text == "Hello world\nRisk"
    assert result.attempt.status == "low_confidence" and result.attempt.confidence == 0.2


def test_valid_empty_ocr_does_not_trigger_text_inference():
    assert parse_tsv("photo", HEADER, Settings()).attempt.status == "empty"


@pytest.mark.parametrize("output", ["", "not tsv", HEADER + "5\t1\t1\t1\t1\t1\tnan\tsecret\n"])
def test_invalid_ocr_response_never_means_empty(output):
    with pytest.raises(ValueError):
        parse_tsv("photo", output, Settings())


def test_ocr_character_limit_is_not_silent_truncation():
    with pytest.raises(ValueError, match="limit"):
        parse_tsv(
            "photo", HEADER + "5\t1\t1\t1\t1\t1\t98\tlong text\n", Settings(max_ocr_characters=2)
        )


@pytest.mark.parametrize(
    "failure", [FileNotFoundError(), subprocess.TimeoutExpired("tesseract", 1)]
)
def test_ocr_dependency_failure_is_explicit(monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("review_jev.ocr.subprocess.run", fail)
    result = TesseractOCR(Settings()).extract("photo", image_uri())
    assert result.attempt.status == "unavailable" and result.text == ""


def test_ocr_uses_stdin_no_shell_or_user_paths(monkeypatch):
    def run(command, **kwargs):
        assert command == ["tesseract", "stdin", "stdout", "-l", "chi_sim+eng", "tsv"]
        assert kwargs["input"].startswith(b"\x89PNG")
        assert "shell" not in kwargs
        return SimpleNamespace(stdout=HEADER.encode())

    monkeypatch.setattr("review_jev.ocr.subprocess.run", run)
    assert TesseractOCR(Settings()).extract("photo", image_uri()).attempt.status == "empty"
    assert (
        TesseractOCR(Settings(ocr_backend="disabled")).extract("photo", image_uri()).attempt.status
        == "disabled"
    )
