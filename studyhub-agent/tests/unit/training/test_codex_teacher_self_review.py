import subprocess

from scripts.data.review_codex_hermes_teacher_samples import (
    invoke_codex,
    stratified_sample,
    summarize,
)


def test_stratified_sample_is_deterministic_and_balanced() -> None:
    rows = [{"id": f"a-{index}", "family": "a"} for index in range(5)] + [
        {"id": f"b-{index}", "family": "b"} for index in range(5)
    ]

    first = stratified_sample(
        rows,
        6,
        seed=17,
        label="accepted",
        family_key="family",
        id_key="id",
    )
    second = stratified_sample(
        rows,
        6,
        seed=17,
        label="accepted",
        family_key="family",
        id_key="id",
    )

    assert first == second
    assert len({row["id"] for row in first}) == 6
    assert sum(row["family"] == "a" for row in first) == 3
    assert sum(row["family"] == "b" for row in first) == 3


def test_summary_never_labels_self_review_as_human_review() -> None:
    rows = [
        {
            "status": "COMPLETE",
            "decision": "ACCEPTED",
            "review": {"verdict": "UPHOLD_ACCEPT"},
        },
        {
            "status": "COMPLETE",
            "decision": "REJECTED",
            "review": {"verdict": "UPHOLD_REJECT"},
        },
    ]

    report = summarize(rows, [])

    assert report["status"] == "COMPLETE"
    assert report["review_type"] == "codex_self_review"
    assert report["independent_human_review"] is False
    assert report["accepted_reviewed"] == 1
    assert report["rejected_reviewed"] == 1


def test_codex_timeout_is_recorded_as_provider_error(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="codex", timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)

    result = invoke_codex(
        {
            "review_id": "review-1",
            "decision": "ACCEPTED",
            "run_id": "run-1",
            "family": "rag",
            "package": {},
        },
        model="gpt-5.6-sol",
        command="codex",
        timeout=1,
    )

    assert result == {
        "review_id": "review-1",
        "status": "PROVIDER_ERROR",
        "error_code": "codex_timeout",
        "decision": "ACCEPTED",
        "run_id": "run-1",
        "family": "rag",
    }


def test_codex_rejects_verdict_for_wrong_original_decision(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def completed(argv, **kwargs):
        output_path = argv[argv.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as stream:
            stream.write('{"verdict":"UPHOLD_REJECT","reason_code":"wrong","brief_explanation":"wrong decision class"}')
        return Result()

    monkeypatch.setattr(subprocess, "run", completed)

    result = invoke_codex(
        {
            "review_id": "review-2",
            "decision": "ACCEPTED",
            "run_id": "run-2",
            "family": "rag",
            "package": {},
        },
        model="gpt-5.6-sol",
        command="codex",
        timeout=1,
    )

    assert result["status"] == "PROVIDER_ERROR"
    assert result["error_code"] == "invalid_verdict_for_decision"
