"""Bridge supported OpenAI metadata into AReaL chat-template kwargs."""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any


METADATA_KEY = "studyhub_chat_template"
DISABLE_THINKING_VALUE = "disable_thinking_v1"
PATCH_MARKER = "_studyhub_metadata_bridge_v1"


def bridge_request_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return request kwargs with the StudyHub template flag applied."""

    metadata = kwargs.get("metadata")
    if not isinstance(metadata, Mapping):
        return kwargs
    if metadata.get(METADATA_KEY) != DISABLE_THINKING_VALUE:
        return kwargs

    bridged = dict(kwargs)
    extra_body = bridged.get("extra_body")
    extra_body = dict(extra_body) if isinstance(extra_body, Mapping) else {}
    template_kwargs = extra_body.get("chat_template_kwargs")
    template_kwargs = (
        dict(template_kwargs) if isinstance(template_kwargs, Mapping) else {}
    )
    template_kwargs["enable_thinking"] = False
    extra_body["chat_template_kwargs"] = template_kwargs
    bridged["extra_body"] = extra_body
    return bridged


def install_areal_metadata_bridge() -> None:
    """Patch the pinned AReaL client without changing upstream source files."""

    from areal.experimental.openai.client import AsyncCompletionsWithReward

    original = AsyncCompletionsWithReward.create
    if getattr(original, PATCH_MARKER, False):
        return

    @functools.wraps(original)
    async def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return await original(self, *args, **bridge_request_kwargs(kwargs))

    setattr(create, PATCH_MARKER, True)
    AsyncCompletionsWithReward.create = create
