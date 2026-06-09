from __future__ import annotations

from dataclasses import asdict
import json

import httpx

from bots.qq_studyhub_bot.config import BotSettings
from bots.qq_studyhub_bot.onebot import OneBotStudyHubBot, format_material_reply, parse_recommendation_query
from bots.qq_studyhub_bot.studyhub_client import MaterialReferral, StudyHubClient


def test_qq_bot_parses_prefixed_recommendation_queries() -> None:
    assert parse_recommendation_query("资料 概率论 真题", prefixes=("资料",)) == "概率论 真题"
    assert parse_recommendation_query("/studyhub 随机信号 期末", prefixes=("/studyhub",)) == "随机信号 期末"
    assert parse_recommendation_query("普通聊天", prefixes=("资料",)) is None


def test_qq_bot_respects_group_allowlist() -> None:
    bot = OneBotStudyHubBot(
        settings=BotSettings(allowed_group_ids=frozenset({10001})),
        studyhub_client=_FakeStudyHubClient(),
    )

    reply = bot.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "group_id": 20002,
            "raw_message": "资料 概率论",
        }
    )

    assert reply is None


def test_qq_bot_refuses_download_delivery_requests() -> None:
    bot = OneBotStudyHubBot(settings=BotSettings(), studyhub_client=_FakeStudyHubClient())

    reply = bot.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "group_id": 10001,
            "raw_message": "资料 概率论 下载链接",
        }
    )

    assert reply is not None
    assert "不能" in reply.message
    assert "代下载" in reply.message


def test_qq_bot_formats_material_links_only() -> None:
    message = format_material_reply(
        query="概率论",
        items=[
            MaterialReferral(
                material_id="51",
                title="概率论真题",
                url="https://study-hub.store/materials/51?ref=qq_bot",
                reason="和检索意图相关。",
                free=False,
                price=1,
                school="电子科技大学",
                college="通识课",
                tags=("真题", "解析"),
                download_count=13,
                rating_avg=4.5,
            )
        ],
    )

    assert "https://study-hub.store/materials/51?ref=qq_bot" in message
    assert "不提供文件下载" in message
    assert "下载链接" not in message
    assert "提取码" not in message


def test_studyhub_client_filters_download_fields_from_api_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/materials"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "items": [
                        {
                            "id": 51,
                            "title": "概率论真题",
                            "free": False,
                            "price": 1,
                            "tags": ["真题"],
                            "downloadUrl": "https://oss.example/signature",
                            "netdiskUrl": "https://pan.example/secret",
                            "netdiskPassword": "abcd",
                        }
                    ]
                },
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = StudyHubClient(
        base_url="https://study-hub.store",
        public_site_base_url="https://study-hub.store",
        http_client=http_client,
    )

    items = client.recommend_materials(query="概率论", limit=1)
    serialized = json.dumps(asdict(items[0]), ensure_ascii=False)

    assert items[0].title == "概率论真题"
    assert items[0].url == "https://study-hub.store/materials/51?ref=qq_bot"
    assert "downloadUrl" not in serialized
    assert "netdiskUrl" not in serialized
    assert "netdiskPassword" not in serialized


class _FakeStudyHubClient:
    def recommend_materials(self, *, query: str | None, limit: int) -> list[MaterialReferral]:
        return [
            MaterialReferral(
                material_id="51",
                title=f"{query or 'StudyHub'} 推荐资料",
                url="https://study-hub.store/materials/51?ref=qq_bot",
                reason="公开目录推荐。",
                free=True,
                price=None,
            )
        ][:limit]
