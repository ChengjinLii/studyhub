from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentic_platform.domain.hashing import canonical_hash
from app.models.agentic_runtime import AgentArtifactRecord, AgentRunRecord
from app.repos.agentic_artifact_repo import AgentArtifactRepository
from app.services.read_support import serialize_datetime


RUNTIME_EVENT_ARTIFACT_TYPE = "runtime_event"
RUNTIME_EVENT_ARTIFACT_KEY_PREFIX = "runtime-events:"
_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SENSITIVE_EVENT_KEYS = frozenset(
    {
        "chain_of_thought",
        "cot",
        "hidden_reasoning",
        "reasoning",
        "thinking",
        "raw_model_output",
        "model_output",
        "raw_prompt",
        "prompt_tokens",
        "token_ids",
        "token_logprobs",
        "api_key",
        "access_token",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
    }
)


class RuntimeEventStore:
    """Append-only, safe-to-display event ledger shared by control and workers.

    Event payloads are intentionally summary-only.  Private chain-of-thought,
    raw model output, credentials, and other sensitive values are never stored
    in this admin-visible ledger.
    """

    def __init__(self, artifacts: AgentArtifactRepository | None = None) -> None:
        self.artifacts = artifacts or AgentArtifactRepository()

    def append(
        self,
        session: Session,
        *,
        run: AgentRunRecord,
        name: str,
        payload: dict[str, Any] | None,
        idempotency_key: str,
    ) -> AgentArtifactRecord:
        if not _EVENT_NAME_RE.fullmatch(name):
            raise ValueError("runtime event name is invalid")
        content = {
            "schemaVersion": "1.0",
            "name": name,
            "payload": safe_public_value(payload or {}),
        }
        event_key = f"{RUNTIME_EVENT_ARTIFACT_KEY_PREFIX}{run.id}"
        record, _created = self.artifacts.create_next_version(
            session,
            thread_id=run.thread_id,
            run_id=run.id,
            admin_actor_id=run.admin_actor_id,
            artifact_type=RUNTIME_EVENT_ARTIFACT_TYPE,
            artifact_key=event_key,
            content=content,
            schema_version="1.0",
            content_hash=canonical_hash(content),
            media_type="application/json",
            idempotency_key=_event_idempotency_key(run.id, idempotency_key),
        )
        return record

    def list_for_run(self, session: Session, run_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        records = list(
            session.scalars(
                select(AgentArtifactRecord)
                .where(
                    AgentArtifactRecord.run_id == run_id,
                    AgentArtifactRecord.artifact_type == RUNTIME_EVENT_ARTIFACT_TYPE,
                    AgentArtifactRecord.artifact_key == f"{RUNTIME_EVENT_ARTIFACT_KEY_PREFIX}{run_id}",
                    AgentArtifactRecord.version > after_sequence,
                )
                .order_by(AgentArtifactRecord.version.asc())
            )
        )
        return [serialize_runtime_event(record) for record in records]

    def latest_sequence(self, session: Session, run_id: str) -> int:
        latest = session.scalar(
            select(AgentArtifactRecord.version)
            .where(
                AgentArtifactRecord.run_id == run_id,
                AgentArtifactRecord.artifact_type == RUNTIME_EVENT_ARTIFACT_TYPE,
                AgentArtifactRecord.artifact_key == f"{RUNTIME_EVENT_ARTIFACT_KEY_PREFIX}{run_id}",
            )
            .order_by(AgentArtifactRecord.version.desc())
            .limit(1)
        )
        return int(latest or 0)


def decode_json(value: str | None, *, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def safe_artifact_preview(content_json: str | None) -> object | None:
    value = decode_json(content_json, fallback=None)
    if value is None:
        return None
    return safe_public_value(value, string_limit=1_200, list_limit=12, dict_limit=24)


def serialize_runtime_event(record: AgentArtifactRecord) -> dict[str, Any]:
    content = decode_json(record.content_json, fallback={})
    if not isinstance(content, dict):
        content = {}
    name = content.get("name") if isinstance(content.get("name"), str) else "runtime.unknown"
    payload = content.get("payload") if isinstance(content.get("payload"), dict) else {}
    return {
        "id": f"{record.run_id}:{record.version}",
        "sequence": record.version,
        "name": name,
        "payload": safe_public_value(payload),
        "occurredAt": serialize_datetime(record.created_at),
    }


def safe_public_value(
    value: Any,
    *,
    depth: int = 0,
    string_limit: int = 2_000,
    list_limit: int = 32,
    dict_limit: int = 48,
) -> Any:
    if depth >= 5:
        return "[truncated]"
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key in sorted(value, key=lambda item: str(item))[:dict_limit]:
            key = str(raw_key)
            normalized_key = key.strip().lower()
            if normalized_key in _SENSITIVE_EVENT_KEYS or any(
                fragment in normalized_key for fragment in ("secret", "token", "password", "credential")
            ):
                safe[key] = "[redacted]"
                continue
            safe[key] = safe_public_value(
                value[raw_key],
                depth=depth + 1,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
        return safe
    if isinstance(value, (list, tuple, set)):
        return [
            safe_public_value(
                item,
                depth=depth + 1,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for item in list(value)[:list_limit]
        ]
    if isinstance(value, str):
        normalized = " ".join(value.split()).strip()
        return normalized[:string_limit]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:string_limit]


def _event_idempotency_key(run_id: str, purpose: str) -> str:
    return f"event:{canonical_hash({'run': run_id, 'purpose': purpose})[:54]}"
