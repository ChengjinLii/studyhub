from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.agents.genrec_agent import GenRecAgent
from ai_platform.harness.tool_policy import ToolPolicy, ToolPolicyError
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents


def test_tool_policy_records_allowed_tool_calls() -> None:
    policy = ToolPolicy()
    policy.require("router.understand", queryLength=10)

    assert policy.records()[0].name == "router.understand"
    assert policy.records()[0].metadata == {"queryLength": 10}


def test_tool_policy_rejects_unknown_tool() -> None:
    policy = ToolPolicy()

    try:
        policy.require("filesystem.write_production_db")
    except ToolPolicyError as exc:
        assert "tool is not allowed" in str(exc)
    else:
        raise AssertionError("unknown tool should be blocked")


def test_genrec_agent_exposes_auditable_tool_use_records() -> None:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))
    response = GenRecAgent(searcher).run("我两周后考通信原理，基础一般，想找速成资料和真题解析。")

    tool_names = [record["name"] for record in response.to_dict()["toolUseRecords"]]

    assert tool_names[0] == "router.understand"
    assert "searchrec.hybrid_retrieval" in tool_names
    assert "reranker.rerank" in tool_names
    assert "genrec.compose" in tool_names
    assert tool_names[-1] == "memory.extract_candidates"


def test_genrec_agent_is_blocked_when_required_tool_is_not_allowed() -> None:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))
    agent = GenRecAgent(searcher, tool_policy=ToolPolicy({"router.understand"}))

    try:
        agent.run("我想找通信原理期末速成资料。")
    except ToolPolicyError as exc:
        assert "searchrec.hybrid_retrieval" in str(exc)
    else:
        raise AssertionError("agent should not run tools outside the allow-list")
