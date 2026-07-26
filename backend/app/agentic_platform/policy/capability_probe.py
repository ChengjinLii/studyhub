from __future__ import annotations

from app.agentic_platform.domain.hashing import canonical_hash

from .model_provider import AgentModelProvider, AgentProviderCapabilities


class CapabilityProbe:
    """Obtains a deterministic capability record before a provider is selected."""

    async def probe(self, provider: AgentModelProvider) -> AgentProviderCapabilities:
        capabilities = await provider.capabilities()
        return capabilities.model_copy(deep=True)

    async def fingerprint(self, provider: AgentModelProvider) -> str:
        return canonical_hash(await self.probe(provider))
