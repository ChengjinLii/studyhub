from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from threading import RLock
from time import time
from typing import Any

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class AgentConversationTurn:
    user: str
    assistant: str
    material_ids: tuple[int, ...] = ()
    created_at: int = 0

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user": self.user,
            "assistant": self.assistant,
        }
        if self.material_ids:
            payload["material_ids"] = list(self.material_ids)
        return payload


class AgentConversationMemoryService:
    """Bounded user-session memory with Redis and in-process fallback.

    Keys always combine the authenticated user id and the validated browser
    session id. Conversation turns never enter platform collective memory.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._entries: OrderedDict[str, tuple[float, list[AgentConversationTurn]]] = OrderedDict()
        self._lock = RLock()
        self._redis_client: Any | None = None

    def load(self, *, user_id: int | None, session_id: str | None) -> list[AgentConversationTurn]:
        if not self._enabled(user_id, session_id):
            return []
        key = self._key(int(user_id), str(session_id))
        redis_turns = self._load_redis(key)
        if redis_turns is not None:
            return redis_turns
        return self._load_local(key)

    def append(
        self,
        *,
        user_id: int | None,
        session_id: str | None,
        user_query: str,
        assistant_answer: str,
        material_ids: list[int] | tuple[int, ...] = (),
    ) -> None:
        if not self._enabled(user_id, session_id):
            return
        turn = AgentConversationTurn(
            user=_clean_memory_text(user_query, max_chars=500),
            assistant=_clean_memory_text(assistant_answer, max_chars=1600),
            material_ids=tuple(dict.fromkeys(int(item) for item in material_ids if int(item) > 0))[:6],
            created_at=int(time()),
        )
        if not turn.user or not turn.assistant:
            return
        key = self._key(int(user_id), str(session_id))
        turns = self.load(user_id=user_id, session_id=session_id)
        turns.append(turn)
        turns = turns[-self._max_turns() :]
        if not self._save_redis(key, turns):
            self._save_local(key, turns)

    def prompt_payload(self, turns: list[AgentConversationTurn]) -> dict[str, Any]:
        if not turns:
            return {}
        return {
            "scope": "authenticated_user_session_only",
            "persistence": "redis_with_bounded_local_fallback",
            "recent_turns": [turn.to_prompt_payload() for turn in turns[-self._max_turns() :]],
            "privacy_boundary": (
                "This conversation memory belongs only to the current authenticated user and session. "
                "Never merge it into platform collective memory or another user session."
            ),
        }

    def context_text(self, turns: list[AgentConversationTurn]) -> str:
        lines: list[str] = []
        for turn in turns[-self._max_turns() :]:
            lines.append(f"用户：{turn.user}")
            lines.append(f"助手：{turn.assistant}")
            if turn.material_ids:
                lines.append("推荐资料：" + " ".join(f"#{item}" for item in turn.material_ids))
        return "\n".join(lines)[-self._max_context_chars() :]

    def clear_user(self, *, user_id: int | None) -> int:
        if user_id is None:
            return 0
        prefix = self._user_key_prefix(int(user_id))
        deleted = self._clear_user_redis(prefix)
        with self._lock:
            local_keys = [key for key in self._entries if key.startswith(prefix)]
            for key in local_keys:
                self._entries.pop(key, None)
            deleted += len(local_keys)
        return deleted

    def _enabled(self, user_id: int | None, session_id: str | None) -> bool:
        return bool(
            getattr(self.settings, "ai_agent_session_memory_enabled", True)
            and user_id is not None
            and session_id
            and re.fullmatch(r"studyhub-agent-[A-Za-z0-9_-]{12,96}", str(session_id))
        )

    def _key(self, user_id: int, session_id: str) -> str:
        digest = sha256(session_id.encode("utf-8")).hexdigest()
        return f"{self._user_key_prefix(user_id)}{digest}"

    def _user_key_prefix(self, user_id: int) -> str:
        namespace = self.settings.redis_namespace.strip(":") or "studyhub-fastapi"
        return f"{namespace}:agent-session-memory:user:{user_id}:"

    def _max_turns(self) -> int:
        return max(2, min(24, int(getattr(self.settings, "ai_agent_session_memory_max_turns", 12) or 12)))

    def _ttl_seconds(self) -> int:
        return max(300, int(getattr(self.settings, "ai_agent_session_memory_ttl_seconds", 604800) or 604800))

    def _max_context_chars(self) -> int:
        return max(600, min(12000, int(getattr(self.settings, "ai_agent_session_memory_max_context_chars", 6000) or 6000)))

    def _load_redis(self, key: str) -> list[AgentConversationTurn] | None:
        client = self._client()
        if client is None:
            return None
        try:
            raw = client.get(key)
            if not raw:
                return []
            return _decode_turns(raw)
        except Exception:
            return None

    def _save_redis(self, key: str, turns: list[AgentConversationTurn]) -> bool:
        client = self._client()
        if client is None:
            return False
        try:
            client.set(key, _encode_turns(turns), ex=self._ttl_seconds())
            return True
        except Exception:
            return False

    def _clear_user_redis(self, prefix: str) -> int:
        client = self._client()
        if client is None:
            return 0
        deleted = 0
        try:
            for key in client.scan_iter(match=f"{prefix}*", count=100):
                deleted += int(client.delete(key) or 0)
        except Exception:
            return deleted
        return deleted

    def _client(self) -> Any | None:
        if not self.settings.redis_url:
            return None
        if self._redis_client is not None:
            return self._redis_client
        try:
            import redis  # type: ignore[import-not-found]

            self._redis_client = redis.Redis.from_url(
                self.settings.redis_url,
                socket_timeout=self.settings.redis_socket_timeout_seconds,
                socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
            )
        except Exception:
            return None
        return self._redis_client

    def _load_local(self, key: str) -> list[AgentConversationTurn]:
        now = time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return []
            expires_at, turns = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return []
            self._entries.move_to_end(key)
            return list(turns)

    def _save_local(self, key: str, turns: list[AgentConversationTurn]) -> None:
        max_sessions = max(
            32,
            min(4096, int(getattr(self.settings, "ai_agent_session_memory_max_sessions", 1024) or 1024)),
        )
        with self._lock:
            self._entries[key] = (time() + self._ttl_seconds(), list(turns))
            self._entries.move_to_end(key)
            while len(self._entries) > max_sessions:
                self._entries.popitem(last=False)


def _encode_turns(turns: list[AgentConversationTurn]) -> str:
    return json.dumps(
        [
            {
                "user": turn.user,
                "assistant": turn.assistant,
                "material_ids": list(turn.material_ids),
                "created_at": turn.created_at,
            }
            for turn in turns
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _decode_turns(value: Any) -> list[AgentConversationTurn]:
    try:
        raw = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    turns: list[AgentConversationTurn] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        user = _clean_memory_text(item.get("user"), max_chars=500)
        assistant = _clean_memory_text(item.get("assistant"), max_chars=1600)
        if not user or not assistant:
            continue
        raw_ids = item.get("material_ids") if isinstance(item.get("material_ids"), list) else []
        material_ids: list[int] = []
        for raw_id in raw_ids[:6]:
            try:
                material_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if material_id > 0 and material_id not in material_ids:
                material_ids.append(material_id)
        turns.append(
            AgentConversationTurn(
                user=user,
                assistant=assistant,
                material_ids=tuple(material_ids),
                created_at=int(item.get("created_at") or 0),
            )
        )
    return turns


def _clean_memory_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"https?://[^\s,;，；。]+|www\.[^\s,;，；。]+", "[redacted-url]", text, flags=re.IGNORECASE)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[redacted-phone]", text)
    text = re.sub(
        r"(?i)(api[_-]?key|token|secret|authorization|bearer)\s*[:=]\s*[^\s,;，；。]+",
        "[redacted-secret]",
        text,
    )
    return text[:max_chars]
