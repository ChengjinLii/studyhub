from __future__ import annotations

import asyncio

from pydantic import ValidationError

from app.repos.agentic_artifact_repo import ArtifactPayloadTooLargeError


class AgentExecutionError(RuntimeError):
    """A stable worker-visible failure without leaking provider internals."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class AgentExecutionPayloadError(AgentExecutionError):
    def __init__(self, code: str = "invalid_agent_execution_payload") -> None:
        super().__init__(code, retryable=False)


class AgentExecutionConfigurationError(AgentExecutionError):
    def __init__(self, code: str = "agent_execution_not_configured") -> None:
        super().__init__(code, retryable=False)


class AgentExecutionLeaseError(AgentExecutionError):
    def __init__(self, code: str = "agent_execution_lease_unavailable") -> None:
        super().__init__(code, retryable=True)


class AgentExecutionTimeoutError(AgentExecutionError):
    def __init__(self, code: str = "agent_execution_timeout") -> None:
        super().__init__(code, retryable=True)


def classify_execution_error(exc: BaseException) -> AgentExecutionError:
    """Map implementation failures to a stable, non-sensitive job error code."""

    if isinstance(exc, AgentExecutionError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return AgentExecutionTimeoutError()
    if isinstance(exc, ArtifactPayloadTooLargeError):
        return AgentExecutionError("agent_execution_artifact_too_large", retryable=False)
    if isinstance(exc, OSError):
        return AgentExecutionError("agent_execution_storage_unavailable", retryable=True)
    if isinstance(exc, (ValidationError, KeyError, TypeError)):
        return AgentExecutionPayloadError()
    return AgentExecutionError("agent_execution_failed", retryable=True)
