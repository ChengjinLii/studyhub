from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_PREFIXES = ("/studyhub", "/sh", "资料", "求资料", "找资料")


@dataclass(frozen=True, slots=True)
class BotSettings:
    studyhub_base_url: str = "https://study-hub.store"
    public_site_base_url: str = "https://study-hub.store"
    onebot_api_base_url: str | None = None
    onebot_access_token: str | None = None
    webhook_secret: str | None = None
    allowed_group_ids: frozenset[int] = frozenset()
    command_prefixes: tuple[str, ...] = DEFAULT_PREFIXES
    max_results: int = 3
    request_timeout_seconds: float = 8.0

    @classmethod
    def from_env(cls) -> "BotSettings":
        studyhub_base_url = _env("STUDYHUB_QQ_BOT_STUDYHUB_BASE_URL", "https://study-hub.store").rstrip("/")
        public_site_base_url = _env("STUDYHUB_QQ_BOT_PUBLIC_SITE_BASE_URL", studyhub_base_url).rstrip("/")
        return cls(
            studyhub_base_url=studyhub_base_url,
            public_site_base_url=public_site_base_url,
            onebot_api_base_url=_optional_env("STUDYHUB_QQ_BOT_ONEBOT_API_BASE_URL"),
            onebot_access_token=_optional_env("STUDYHUB_QQ_BOT_ONEBOT_ACCESS_TOKEN"),
            webhook_secret=_optional_env("STUDYHUB_QQ_BOT_WEBHOOK_SECRET"),
            allowed_group_ids=_parse_group_ids(_optional_env("STUDYHUB_QQ_BOT_ALLOWED_GROUP_IDS")),
            command_prefixes=_parse_prefixes(_optional_env("STUDYHUB_QQ_BOT_COMMAND_PREFIXES")),
            max_results=_parse_int(_optional_env("STUDYHUB_QQ_BOT_MAX_RESULTS"), default=3, minimum=1, maximum=6),
            request_timeout_seconds=float(_optional_env("STUDYHUB_QQ_BOT_TIMEOUT_SECONDS") or "8"),
        )


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_group_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    group_ids: set[int] = set()
    for chunk in raw.split(","):
        value = chunk.strip()
        if value:
            group_ids.add(int(value))
    return frozenset(group_ids)


def _parse_prefixes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_PREFIXES
    prefixes = tuple(prefix.strip() for prefix in raw.split(",") if prefix.strip())
    return prefixes or DEFAULT_PREFIXES


def _parse_int(raw: str | None, *, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    return max(minimum, min(int(raw), maximum))

