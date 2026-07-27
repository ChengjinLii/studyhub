from __future__ import annotations

from app.core.config import Settings

from .model_provider import AgentModelProvider
from .openai_compatible_provider import OpenAICompatibleProvider
from .token_trace import TokenTraceSource


class AgentModelProviderConfigurationError(ValueError):
    """Raised before a worker starts when the opt-in model plane is incomplete."""


def build_agent_model_provider(settings: Settings) -> AgentModelProvider:
    provider = settings.agentic_model_provider.strip().lower()
    if provider != "openai_compatible":
        raise AgentModelProviderConfigurationError("agentic model provider is disabled or unsupported")
    missing = [
        variable
        for variable, value in (
            ("STUDYHUB_AGENTIC_MODEL_BASE_URL", settings.agentic_model_base_url),
            ("STUDYHUB_AGENTIC_MODEL_API_KEY", settings.agentic_model_api_key),
            ("STUDYHUB_AGENTIC_MODEL_ID", settings.agentic_model_id),
        )
        if not value or not value.strip()
    ]
    if missing:
        raise AgentModelProviderConfigurationError(f"missing agentic model configuration: {', '.join(missing)}")
    try:
        trace_source = TokenTraceSource(settings.agentic_model_token_trace_source)
    except ValueError as exc:
        raise AgentModelProviderConfigurationError("invalid agentic model token trace source") from exc
    return OpenAICompatibleProvider(
        base_url=settings.agentic_model_base_url or "",
        api_key=settings.agentic_model_api_key or "",
        model_id=settings.agentic_model_id or "",
        timeout_seconds=settings.agentic_model_timeout_seconds,
        max_retries=settings.agentic_model_max_retries,
        model_revision=settings.agentic_model_revision,
        token_trace_source=trace_source,
    )
