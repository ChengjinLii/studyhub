from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime, time
from enum import Enum
from typing import Any

from pydantic import BaseModel


NONDETERMINISTIC_EXPORT_FIELDS = frozenset({"exported_at", "trace_exported_at", "trace_export_time"})


def canonicalize(value: Any, *, exclude_fields: Iterable[str] = NONDETERMINISTIC_EXPORT_FIELDS) -> Any:
    """Convert a domain value into deterministic, JSON-safe data.

    Export timestamps describe when a trace was copied, rather than the business
    event that happened.  They are deliberately omitted while business timestamps
    such as `captured_at` and `business_time` remain part of the hash.
    """

    excluded = frozenset(exclude_fields)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, dict):
        return {
            str(key): canonicalize(item, exclude_fields=excluded)
            for key, item in value.items()
            if str(key) not in excluded
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item, exclude_fields=excluded) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(canonicalize(item, exclude_fields=excluded) for item in value)
    if isinstance(value, Enum):
        return canonicalize(value.value, exclude_fields=excluded)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def canonical_json(value: Any, *, exclude_fields: Iterable[str] = NONDETERMINISTIC_EXPORT_FIELDS) -> str:
    """Return sorted UTF-8 JSON with compact separators for stable hashing."""

    return json.dumps(
        canonicalize(value, exclude_fields=exclude_fields),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: Any, *, exclude_fields: Iterable[str] = NONDETERMINISTIC_EXPORT_FIELDS) -> str:
    return hashlib.sha256(canonical_json(value, exclude_fields=exclude_fields).encode("utf-8")).hexdigest()


def canonical_model_hash(model: BaseModel) -> str:
    return canonical_hash(model)


def json_schema_hash(model_type: type[BaseModel]) -> str:
    """Fingerprint an exported Pydantic JSON schema without depending on order."""

    return canonical_hash(model_type.model_json_schema(), exclude_fields=())
