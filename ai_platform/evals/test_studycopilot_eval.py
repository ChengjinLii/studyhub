from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.scripts.studycopilot_eval import run_eval


def test_studycopilot_eval_runner_passes_v9_acceptance_suite() -> None:
    report = run_eval()

    assert report["suite"] == "studycopilot-v9-offline"
    assert report["passed"] is True
    assert report["caseCount"] == 6
    assert report["passedCount"] == 6
    for case in report["cases"]:
        assert case["passed"] is True
        check_names = {check["name"] for check in case["checks"]}
        assert "cited_ids_from_retrieval" in check_names
        assert "no_private_contact_in_ai_output" in check_names
        if "prompt_injection_warning_present" in check_names:
            assert "no_secret_terms_in_answer" in check_names
        else:
            assert "feedback_hooks_complete" in check_names
            assert "expected_recommended_id_present" in check_names
