import pytest

from studyhub_agent.rewards import RewardSignals, evaluate_reward
from studyhub_agent.rewards.schema import RewardResult


def test_reward_is_deterministic_and_rewards_grounded_success() -> None:
    signals = RewardSignals(
        final_answer="建议先复习调制，再刷真题。[source:material:101:p1:c0]",
        verifier={"expected_contains": ["调制", "真题"], "citations_required": True},
        available_source_ids=frozenset({"material:101:p1:c0"}),
        supported_claims=2,
        total_claims=2,
        valid_tool_calls=2,
        total_tool_calls=2,
        required_tool_calls=1,
        steps=4,
        max_steps=8,
    )

    first = evaluate_reward(signals)
    second = evaluate_reward(signals)

    assert first == second
    assert first.task_success == 1.0
    assert first.groundedness == 1.0
    assert first.citation == 1.0
    assert first.total > 0.7
    assert first.violations == []


def test_reward_penalizes_invalid_citation_duplicate_calls_and_acl_violation() -> None:
    result = evaluate_reward(
        RewardSignals(
            final_answer="这是未经授权的结论。[source:material:999:p1:c0]",
            verifier={"expected_contains": ["正确内容"], "citations_required": True},
            available_source_ids=frozenset({"material:101:p1:c0"}),
            supported_claims=0,
            total_claims=1,
            valid_tool_calls=1,
            total_tool_calls=2,
            required_tool_calls=1,
            duplicate_tool_calls=1,
            steps=8,
            max_steps=8,
            premature_final=True,
            boundary_violations=("acl_violation",),
        )
    )

    assert result.total == -1.0
    assert set(result.violations) == {"acl_violation", "invalid_citation", "premature_final"}


def test_reward_result_rejects_out_of_range_component() -> None:
    with pytest.raises(ValueError):
        RewardResult(1.1, 1, 1, 1, 1, 1, [])
