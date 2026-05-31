from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.router.query_understanding import LLMQueryUnderstandingRouter, parse_query_understanding_json
from ai_platform.serving.llm_provider import ChatCompletionResponse


class FakeChatProvider:
    name = "fake-chat"
    model = "fake-model"

    def __init__(self, content: str, *, should_fail: bool = False) -> None:
        self.content = content
        self.should_fail = should_fail

    def complete(self, _request):
        if self.should_fail:
            raise RuntimeError("forced failure")
        return ChatCompletionResponse(provider=self.name, model=self.model, content=self.content, usage={})


def test_parse_query_understanding_json_validates_tasks_and_entities() -> None:
    result = parse_query_understanding_json(
        "我两周后考通信原理，基础一般，想找速成资料和真题解析。",
        """
        {
          "intent": "study_plan",
          "queryRewrite": "通信原理 期末 真题 速成",
          "entities": {
            "course": "通信原理",
            "examTime": "两周后",
            "level": "基础一般",
            "materialTypes": ["速成资料", "真题解析"]
          },
          "searchTasks": [
            {"type": "material", "query": "通信原理 期末 速成 笔记", "topK": 5},
            {"type": "column", "query": "通信原理 复习 经验", "topK": 3}
          ],
          "suggestions": ["通信原理两周复习计划"]
        }
        """,
    )

    assert result.intent == "study_plan"
    assert result.entities.course == "通信原理"
    assert result.entities.material_types == ("速成资料", "真题解析")
    assert result.search_tasks[0].type == "material"
    assert result.search_tasks[1].type == "column"
    assert not result.fallback_used


def test_llm_router_falls_back_when_provider_fails() -> None:
    router = LLMQueryUnderstandingRouter(FakeChatProvider("{}", should_fail=True))

    result = router.understand("我想找通信原理期末速成资料。")

    assert result.intent == "material_search"
    assert result.fallback_used
    assert any(warning.startswith("llm_router_fallback") for warning in result.warnings)


def test_llm_router_uses_provider_json_when_valid() -> None:
    router = LLMQueryUnderstandingRouter(
        FakeChatProvider(
            '{"intent":"request_search","queryRewrite":"数据结构 实验报告 求购","entities":{"course":"数据结构","materialTypes":["实验报告"]},"searchTasks":[{"type":"request","query":"数据结构 实验报告 模板","topK":5}],"suggestions":["数据结构实验报告模板"]}'
        )
    )

    result = router.understand("有没有数据结构实验报告模板？")

    assert result.intent == "request_search"
    assert result.entities.course == "数据结构"
    assert result.search_tasks[0].type == "request"
    assert result.suggestions == ("数据结构实验报告模板",)
