from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_memory_service import AgentMemoryContext
from app.services.agent_conversation_memory_service import AgentConversationMemoryService
from app.services.ai_service import AiService


def _service(**overrides: object) -> AgentConversationMemoryService:
    return AgentConversationMemoryService(
        Settings(
            ai_agent_session_memory_enabled=True,
            ai_agent_session_memory_max_turns=3,
            ai_agent_session_memory_ttl_seconds=600,
            **overrides,
        )
    )


def test_conversation_memory_is_isolated_by_user_and_session() -> None:
    service = _service()
    session_id = "studyhub-agent-7-abcdef1234567890"
    service.append(
        user_id=7,
        session_id=session_id,
        user_query="两周后考通信原理",
        assistant_answer="先补框架，再刷真题。",
        material_ids=[101, 102],
    )

    own_turns = service.load(user_id=7, session_id=session_id)
    assert [turn.user for turn in own_turns] == ["两周后考通信原理"]
    assert own_turns[0].material_ids == (101, 102)
    assert service.load(user_id=8, session_id=session_id) == []
    assert service.load(user_id=7, session_id="studyhub-agent-7-other123456789") == []


def test_conversation_memory_is_bounded_and_redacts_sensitive_text() -> None:
    service = _service()
    session_id = "studyhub-agent-7-abcdef1234567890"
    for index in range(5):
        service.append(
            user_id=7,
            session_id=session_id,
            user_query=f"第 {index} 轮，邮箱 alice@example.com",
            assistant_answer=f"第 {index} 轮回答，电话 13812345678",
        )

    turns = service.load(user_id=7, session_id=session_id)
    assert len(turns) == 3
    assert turns[0].user.startswith("第 2 轮")
    serialized = service.context_text(turns)
    assert "alice@example.com" not in serialized
    assert "13812345678" not in serialized
    assert "[redacted-email]" in serialized
    assert "[redacted-phone]" in serialized


def test_conversation_memory_can_clear_one_user_without_touching_another() -> None:
    service = _service()
    sessions = ["studyhub-agent-7-abcdef1234567890", "studyhub-agent-7-zxcvbn1234567890"]
    for session_id in sessions:
        service.append(
            user_id=7,
            session_id=session_id,
            user_query="通信原理复习",
            assistant_answer="继续按计划复习。",
        )
    service.append(
        user_id=8,
        session_id=sessions[0],
        user_query="ESD 复习",
        assistant_answer="先看课程框架。",
    )

    assert service.clear_user(user_id=7) == 2
    assert service.load(user_id=7, session_id=sessions[0]) == []
    assert service.load(user_id=7, session_id=sessions[1]) == []
    assert len(service.load(user_id=8, session_id=sessions[0])) == 1


def test_conversation_memory_prompt_declares_user_platform_boundary() -> None:
    service = _service()
    session_id = "studyhub-agent-7-abcdef1234567890"
    service.append(
        user_id=7,
        session_id=session_id,
        user_query="继续细化前七天",
        assistant_answer="第 1-7 天按每天两小时安排。",
    )

    payload = service.prompt_payload(service.load(user_id=7, session_id=session_id))
    assert payload["scope"] == "authenticated_user_session_only"
    assert "Never merge" in payload["privacy_boundary"]
    assert payload["recent_turns"][0]["user"] == "继续细化前七天"


def test_ai_service_merges_session_memory_into_user_layer_only() -> None:
    settings = Settings(ai_agent_session_memory_enabled=True)
    conversations = AgentConversationMemoryService(settings)
    session_id = "studyhub-agent-7-abcdef1234567890"
    conversations.append(
        user_id=7,
        session_id=session_id,
        user_query="两周后考通信原理",
        assistant_answer="已经给出第一版计划。",
    )

    class FakeMemoryService:
        def collect(self, session: object, **kwargs: object) -> AgentMemoryContext:
            del session, kwargs
            return AgentMemoryContext(
                platform={"course_signals": [{"value": "通信原理", "count": 3}]},
                user={"profile": {"major": "通信工程"}},
            )

    service = AiService(
        read_repo=None,
        material_repo=None,
        memory_service=FakeMemoryService(),  # type: ignore[arg-type]
        conversation_memory_service=conversations,
    )  # type: ignore[arg-type]
    turns = conversations.load(user_id=7, session_id=session_id)
    context = service._collect_memory_context(  # noqa: SLF001
        object(),  # type: ignore[arg-type]
        query="继续细化",
        materials=[],
        current_user_id=7,
        pdf_evidence=[],
        conversation_turns=turns,
    )

    assert context is not None
    assert "conversation_memory" not in context.platform
    assert context.user is not None
    assert context.user["profile"]["major"] == "通信工程"
    assert context.user["conversation_memory"]["recent_turns"][0]["user"] == "两周后考通信原理"


def test_ai_service_remembers_sanitized_completed_turn(monkeypatch) -> None:
    settings = Settings(ai_agent_provider="local", ai_agent_session_memory_enabled=True)
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    conversations = AgentConversationMemoryService(settings)
    service = AiService(
        read_repo=None,
        material_repo=None,
        conversation_memory_service=conversations,
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            MaterialRecord(id=101, title="通信原理真题解析", description="期末真题和解析", is_free=True)
        ],
    )
    session_id = "studyhub-agent-7-abcdef1234567890"

    service.recommend(
        object(),  # type: ignore[arg-type]
        type(
            "Payload",
            (),
            {
                "query": "两周后考通信原理，怎么复习",
                "filters": {},
                "contextQuery": None,
                "sessionId": session_id,
                "imageAttachments": [],
            },
        )(),
        current_user_id=7,
    )

    turns = conversations.load(user_id=7, session_id=session_id)
    assert len(turns) == 1
    assert turns[0].user == "两周后考通信原理，怎么复习"
    assert turns[0].material_ids == (101,)
