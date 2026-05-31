from __future__ import annotations

from typing import Any

from ai_platform.preprocessing.ai_document import redact_contacts


def sanitize_for_model(value: Any) -> Any:
    """Remove direct contact details before sending data to a model provider."""

    if isinstance(value, str):
        return redact_contacts(value)
    if isinstance(value, list):
        return [sanitize_for_model(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_model(item) for item in value)
    if isinstance(value, dict):
        return {str(key): sanitize_for_model(item) for key, item in value.items()}
    return value
