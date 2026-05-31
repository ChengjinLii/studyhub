from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.scripts.studycopilot_demo import run_studycopilot


def test_studycopilot_runs_full_loop_for_study_plan() -> None:
    result = run_studycopilot("我两周后考通信原理，基础一般，想找速成资料和真题解析。")

    assert result["understanding"]["intent"] == "study_plan"
    assert result["understanding"]["queryRewrite"]
    assert result["retrievedCandidates"]
    assert result["rerankedCandidates"]
    assert result["recommendedItems"]
    assert result["studyPlan"]
    assert result["feedbackHooks"]
    assert result["memoryCandidates"]
    assert result["recommendedItems"][0]["id"] in {"material-001", "column-001", "request-001"}


def test_studycopilot_supports_v9_acceptance_queries() -> None:
    queries = [
        "我想找通信原理期末速成资料。",
        "有没有数据结构实验报告模板？",
        "我想求购高数下历年真题。",
        "我两周后考试，基础一般，帮我安排复习。",
        "这道链表题为什么我写错了？",
    ]

    for query in queries:
        result = run_studycopilot(query)
        assert result["understanding"]["intent"]
        assert result["understanding"]["queryRewrite"]
        assert isinstance(result["understanding"]["entities"], dict)
        assert result["retrievedCandidates"]
        assert result["rerankedCandidates"]
        assert result["answer"]
        assert result["feedbackHooks"]
        cited_ids = {item["id"] for item in result["recommendedItems"]}
        retrieved_ids = {item["id"] for item in result["retrievedCandidates"]}
        assert cited_ids
        assert cited_ids <= retrieved_ids


def test_question_help_generates_study_steps_without_inventing_ids() -> None:
    result = run_studycopilot("这道链表题为什么我写错了？")

    assert result["understanding"]["intent"] == "question_help"
    assert result["studyPlan"]
    cited_ids = {item["id"] for item in result["recommendedItems"]}
    reranked_ids = {item["id"] for item in result["rerankedCandidates"]}
    assert cited_ids <= reranked_ids
