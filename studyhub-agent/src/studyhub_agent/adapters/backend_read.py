from __future__ import annotations

from typing import Protocol

from studyhub_agent.guardrails.permissions import PermissionContext


class BackendReadProvider(Protocol):
    """Future read-only boundary for production metadata and entitlement snapshots."""

    async def permission_context(self, principal_id: str) -> PermissionContext: ...
