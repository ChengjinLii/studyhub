from studyhub_agent.runtime.profile import AgentProfile
from studyhub_agent.runtime.session import TaskSpec


def test_task_spec_round_trip_and_defensive_copies() -> None:
    task = TaskSpec(
        task_id="case-001",
        family="rag_only",
        difficulty="medium",
        user_request="帮我找通信原理资料",
        environment_seed=6209,
        allowed_tools=["knowledge_search", "knowledge_read", "knowledge_search"],
        max_steps=8,
        max_tool_calls=5,
        metadata={"course": "通信原理"},
        verifier={"expected_sources": ["material:128:p12:c3"]},
    )

    assert task.allowed_tools == ["knowledge_search", "knowledge_read"]
    assert TaskSpec.from_dict(task.to_dict()) == task


def test_agent_profile_round_trip() -> None:
    profile = AgentProfile(
        prompt_version="studyhub-v2",
        tool_schema_version="v1",
        max_turns=12,
        max_tool_calls=8,
        enabled_capabilities=["knowledge", "web", "knowledge"],
    )

    assert profile.enabled_capabilities == ["knowledge", "web"]
    assert AgentProfile.from_dict(profile.to_dict()) == profile
