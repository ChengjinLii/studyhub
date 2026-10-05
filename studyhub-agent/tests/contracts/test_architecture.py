from types import MappingProxyType

import pytest

from studyhub_agent.contracts.architecture import RunContext
from studyhub_agent.contracts.episode import EpisodeSpec, Observation, Principal


@pytest.mark.parametrize(
    "evidence", [None, False, 101, "101:1", [[], [101], [101, 1, 2]], [[True, 1], [101, 0], [-1, 1], ["101", 1]]]
)
def test_malformed_read_evidence_does_not_validate_citations(evidence) -> None:
    context = RunContext(
        spec=EpisodeSpec(
            episode_id="ep", task_id="t", user_message="q", principal=Principal(principal_id="p"), tool_names=()
        ),
        turns=(),
        prompts=MappingProxyType({}),
        trace={},
        observations=(
            Observation(call_id="c", name="materials_read", ok=True, payload={}, details={"read_pages": evidence}),
        ),
    )
    assert context.read_pages == frozenset()


def test_other_tools_cannot_claim_to_have_read_pages() -> None:
    context = RunContext(
        spec=EpisodeSpec(
            episode_id="ep", task_id="t", user_message="q", principal=Principal(principal_id="p"), tool_names=()
        ),
        turns=(),
        prompts=MappingProxyType({}),
        trace={},
        observations=(
            Observation(call_id="c", name="materials_search", ok=True, payload={}, details={"read_pages": [[101, 1]]}),
        ),
    )
    assert context.read_pages == frozenset()
