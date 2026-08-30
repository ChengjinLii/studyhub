from pathlib import Path

import pytest

from studyhub_agent.adapters.collective_memory import FixtureCollectiveMemoryReader
from studyhub_agent.adapters.personal_memory import InMemoryPersonalMemoryProvider
from studyhub_agent.adapters.rag import RagExperimentKnowledgeRetriever
from studyhub_agent.guardrails.permissions import PermissionContext
from studyhub_agent.guardrails.web_security import WebSecurityPolicy
from studyhub_agent.replay.web_providers import (
    FixtureWebFetchProvider,
    FixtureWebSearchProvider,
    GuardedWebProviders,
)
from studyhub_agent.runtime.identity import AgentIdentity

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_SECRET = "phase1-fixture-identity-secret"


@pytest.fixture
def project_root() -> Path:
    return ROOT


@pytest.fixture
def identity() -> AgentIdentity:
    return AgentIdentity.from_raw_user_id(
        "fixture-user",
        session_id="fixture-session-0001",
        environment="eval",
        identity_secret=IDENTITY_SECRET,
    )


@pytest.fixture
def permissions(identity: AgentIdentity) -> PermissionContext:
    return PermissionContext(principal_id=identity.principal_id)


@pytest.fixture
def knowledge(project_root: Path) -> RagExperimentKnowledgeRetriever:
    return RagExperimentKnowledgeRetriever.from_jsonl(project_root / "fixtures/rag/chunks.jsonl")


def fixture_resolver(hostname: str) -> list[str]:
    if hostname in {"docs.example.edu", "standards.example.org"}:
        return ["93.184.216.34"]
    return ["127.0.0.1"]


@pytest.fixture
def web(project_root: Path) -> GuardedWebProviders:
    return GuardedWebProviders(
        search_provider=FixtureWebSearchProvider.from_json(project_root / "fixtures/web/search.json"),
        fetch_provider=FixtureWebFetchProvider.from_json(project_root / "fixtures/web/pages.json"),
        policy=WebSecurityPolicy(max_redirects=2, max_response_bytes=10_000),
        resolver=fixture_resolver,
    )


@pytest.fixture
def personal_memory() -> InMemoryPersonalMemoryProvider:
    return InMemoryPersonalMemoryProvider()


@pytest.fixture
def collective_memory(project_root: Path) -> FixtureCollectiveMemoryReader:
    return FixtureCollectiveMemoryReader.from_json(project_root / "fixtures/memory/collective.json")
