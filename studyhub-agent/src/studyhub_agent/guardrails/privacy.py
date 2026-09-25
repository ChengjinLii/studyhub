from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

FORBIDDEN_KEYS = frozenset({"email", "phone", "username", "raw_user_id", "user_id", "chat_transcript", "id_card"})
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def redact_text(value: str) -> str:
    return EMAIL_PATTERN.sub("[redacted-email]", value)


def sanitize_output(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_output(item)
            for key, item in value.items()
            if str(key).strip().lower() not in FORBIDDEN_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [sanitize_output(item) for item in value]
    return value
