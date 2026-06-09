from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import httpx

from bots.qq_studyhub_bot.config import BotSettings
from bots.qq_studyhub_bot.studyhub_client import MaterialReferral, StudyHubClient


DOWNLOAD_INTENT_PATTERN = re.compile(r"(下载|网盘|提取码|直链|发我文件|发文件|白嫖|破解|绕过|免登录)")
CQ_CODE_PATTERN = re.compile(r"\[CQ:[^\]]+\]")


@dataclass(slots=True)
class BotReply:
    group_id: int
    message: str


class OneBotStudyHubBot:
    def __init__(self, *, settings: BotSettings, studyhub_client: StudyHubClient | None = None) -> None:
        self.settings = settings
        self.studyhub_client = studyhub_client or StudyHubClient(
            base_url=settings.studyhub_base_url,
            public_site_base_url=settings.public_site_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        )

    def handle_event(self, event: dict[str, Any]) -> BotReply | None:
        if event.get("post_type") != "message" or event.get("message_type") != "group":
            return None
        group_id = _safe_int(event.get("group_id"))
        if group_id <= 0:
            return None
        if self.settings.allowed_group_ids and group_id not in self.settings.allowed_group_ids:
            return None
        text = extract_message_text(event)
        query = parse_recommendation_query(text, prefixes=self.settings.command_prefixes)
        if query is None:
            return None
        if DOWNLOAD_INTENT_PATTERN.search(query):
            return BotReply(
                group_id=group_id,
                message="我只能推荐 StudyHub 资料页链接，不能在 QQ 群里代下载、发网盘或绕过付费。请打开站内链接后按平台流程查看、购买或下载。",
            )
        if not query:
            return BotReply(group_id=group_id, message="请带上课程名、关键词或考试方向，例如：资料 概率论 真题")
        referrals = self.studyhub_client.recommend_materials(query=query, limit=self.settings.max_results)
        return BotReply(group_id=group_id, message=format_material_reply(query=query, items=referrals))

    def send_group_message(self, reply: BotReply) -> None:
        if not self.settings.onebot_api_base_url:
            return
        url = f"{self.settings.onebot_api_base_url.rstrip('/')}/send_group_msg"
        headers = {}
        if self.settings.onebot_access_token:
            headers["Authorization"] = f"Bearer {self.settings.onebot_access_token}"
        payload = {
            "group_id": reply.group_id,
            "message": reply.message,
            "auto_escape": False,
        }
        with httpx.Client(timeout=self.settings.request_timeout_seconds, trust_env=False) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()


def extract_message_text(event: dict[str, Any]) -> str:
    raw = event.get("raw_message")
    if isinstance(raw, str) and raw.strip():
        return _normalize_message(raw)
    message = event.get("message")
    if isinstance(message, list):
        chunks: list[str] = []
        for segment in message:
            if not isinstance(segment, dict):
                continue
            if segment.get("type") == "text":
                data = segment.get("data")
                if isinstance(data, dict):
                    chunks.append(str(data.get("text") or ""))
        return _normalize_message(" ".join(chunks))
    return ""


def parse_recommendation_query(text: str, *, prefixes: tuple[str, ...]) -> str | None:
    normalized = _normalize_message(text)
    if not normalized:
        return None
    for prefix in prefixes:
        if normalized == prefix:
            return ""
        if normalized.startswith(prefix):
            return _clean_query(normalized[len(prefix) :])
    return None


def format_material_reply(*, query: str, items: list[MaterialReferral]) -> str:
    if not items:
        return f"暂时没有找到和“{query}”直接相关的资料。可以换个课程名、老师名、题型或关键词再试。"
    lines = [f"StudyHub 为“{query}”找到 {len(items)} 份资料："]
    for index, item in enumerate(items, start=1):
        meta = _material_meta(item)
        lines.extend(
            [
                f"{index}. {item.title}",
                f"   {meta}",
                f"   推荐理由：{item.reason}",
                f"   链接：{item.url}",
            ]
        )
    lines.append("提示：这里只推荐站内资料页链接，不提供文件下载。登录、购买和下载请在 StudyHub 页面完成。")
    return "\n".join(lines)


def _material_meta(item: MaterialReferral) -> str:
    price = "免费" if item.free else _format_price(item.price)
    parts = [price]
    if item.school:
        parts.append(item.school)
    if item.college:
        parts.append(item.college)
    if item.tags:
        parts.append(" / ".join(item.tags))
    if item.download_count:
        parts.append(f"下载 {item.download_count}")
    if item.rating_avg:
        parts.append(f"评分 {item.rating_avg:.1f}")
    return " · ".join(parts)


def _format_price(value: int | float | None) -> str:
    if value is None:
        return "付费"
    try:
        return f"¥{float(value):g}"
    except (TypeError, ValueError):
        return "付费"


def _normalize_message(value: str) -> str:
    without_cq = CQ_CODE_PATTERN.sub(" ", value)
    return " ".join(without_cq.strip().split())


def _clean_query(value: str) -> str:
    query = value.strip(" ：:，,")
    return query[:80].strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

