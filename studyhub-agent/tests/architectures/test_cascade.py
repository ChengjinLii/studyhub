import json

import pytest

from studyhub_agent.architectures import CascadeArchitecture
from studyhub_agent.architectures.cascade import cascade_token_cost
from studyhub_agent.contracts.episode import Budget, Termination
from studyhub_agent.environments.replay import ReplayEnvironment
from tests.architectures.test_hooks import RUNNER, SNAPSHOT, _spec
from tests.runtime.fakes import ScriptedPolicy, count_chars, final_turn, parse_error_turn, tool_turn


def _run(small_turns, large_turns, *, architecture=None, spec=None, counters=None):
    small, large = ScriptedPolicy(list(small_turns)), ScriptedPolicy(list(large_turns))
    episode = RUNNER.run(
        spec or _spec(),
        ReplayEnvironment(SNAPSHOT),
        small,
        architecture=architecture or CascadeArchitecture(),
        policies={"small": small, "large": large},
        models={"small": "Qwen/Qwen3.5-4B", "large": "Qwen/Qwen3.5-9B"},
        model_revisions={"small": "4b-rev", "large": "9b-rev"},
        token_counters=counters or {"small": count_chars, "large": count_chars},
    )
    return episode, small, large


def test_normal_episode_uses_small_model_only() -> None:
    episode, _, large = _run([final_turn("信息不足，查不到")], [])
    assert episode.architecture == "cascade@1.0" and episode.final_answer == "信息不足，查不到"
    assert large.seen == [] and "escalated_at" not in episode.architecture_trace
    assert episode.turns[0].policy_key == "small"


def test_parse_error_escalates_once_and_transfers_complete_history() -> None:
    episode, _, large = _run(
        [parse_error_turn()],
        [tool_turn(("materials_search", {"query": "提纲"})), final_turn("答案")],
    )
    assert episode.final_answer == "答案"
    assert episode.architecture_trace["escalation_reason"] == "parse_error"
    assert episode.architecture_trace["escalated_at"] == 1
    assert [(turn.policy_key, turn.model_id) for turn in episode.turns] == [
        ("small", "Qwen/Qwen3.5-4B"),
        ("large", "Qwen/Qwen3.5-9B"),
        ("large", "Qwen/Qwen3.5-9B"),
    ]
    assert large.seen[0] == episode.messages[:4]
    assert json.loads(large.seen[0][-1].content)["error"] == "malformed_tool_call"


@pytest.mark.parametrize("metric", ["tool_calls", "turns"])
def test_budget_threshold_escalates_at_exact_boundary(metric) -> None:
    spec = _spec(
        budget=Budget(max_turns=2 if metric == "turns" else 12, max_tool_calls=16 if metric == "turns" else 2)
    )
    architecture = CascadeArchitecture(escalate_ratio=0.5)
    episode, _, large = _run(
        [tool_turn(("materials_search", {"query": "提纲"}))],
        [final_turn("答案")],
        architecture=architecture,
        spec=spec,
    )
    assert episode.architecture_trace["escalation_reason"] == metric
    assert episode.architecture_trace["escalated_at"] == 1
    assert large.seen and episode.termination is Termination.FINAL_ANSWER


def test_citation_failure_escalates_and_large_model_repairs() -> None:
    episode, _, large = _run(
        [
            tool_turn(("materials_search", {"query": "提纲"})),
            tool_turn(("materials_read", {"material_id": 101})),
            final_turn("错误 [101:2]"),
        ],
        [final_turn("正确 [101:1]")],
    )
    assert episode.final_answer == "正确 [101:1]"
    assert episode.architecture_trace["escalation_reason"] == "citation"
    assert episode.architecture_trace["escalated_at"] == 3
    assert episode.architecture_trace["citation_verified"] is True
    assert json.loads(large.seen[0][-1].content)["notice"] == "citation_check_failed"
    assert large.seen[0] == episode.messages[:-1]


def test_repair_limit_is_shared_across_small_and_large_models() -> None:
    episode, _, large = _run(
        [final_turn("错误 [101:2]")],
        [final_turn("仍错 [101:2]"), final_turn("仍然错误 [101:2]")],
    )
    assert len(large.seen) == 2 and len(episode.turns) == 3
    assert episode.architecture_trace["verify_rejections"] == 2
    assert episode.architecture_trace["citation_verified"] is False
    assert episode.architecture_trace["verify_limit_reached"] is True
    assert episode.architecture_trace["escalated_at"] == 1


def test_zero_repair_budget_accepts_unverified_answer_without_phantom_escalation() -> None:
    episode, _, large = _run([final_turn("[101:2]")], [], architecture=CascadeArchitecture(max_rejections=0))
    assert episode.architecture_trace["citation_verified"] is False
    assert episode.architecture_trace["verify_limit_reached"] is True
    assert large.seen == [] and "escalated_at" not in episode.architecture_trace


def test_rejected_last_turn_does_not_exceed_budget_or_claim_actual_escalation() -> None:
    episode, _, large = _run([final_turn("[101:2]")], [], spec=_spec(budget=Budget(max_turns=1)))
    assert episode.termination is Termination.MAX_TURNS and episode.final_answer is None
    assert "escalated_at" not in episode.architecture_trace and large.seen == []
    assert episode.architecture_trace["escalation_pending"] == "citation"


def test_escalated_policy_uses_its_own_token_counter_before_generation() -> None:
    episode, _, large = _run(
        [parse_error_turn()],
        [],
        counters={"small": count_chars, "large": lambda *_args: 100_000},
    )
    assert episode.termination is Termination.CONTEXT_BUDGET and large.seen == []


def test_missing_large_policy_is_rejected_before_reset() -> None:
    class NeverReset(ReplayEnvironment):
        def reset(self, spec):
            pytest.fail("invalid configuration must not reset environment")

    with pytest.raises(ValueError, match="requires.*large"):
        RUNNER.run(_spec(), NeverReset(SNAPSHOT), ScriptedPolicy([]), architecture=CascadeArchitecture())


def test_cascade_state_is_isolated_between_episodes() -> None:
    architecture = CascadeArchitecture()
    switched, _, _ = _run([parse_error_turn()], [final_turn("答案")], architecture=architecture)
    normal, _, large = _run([final_turn("答案")], [], architecture=architecture)
    assert "escalated_at" in switched.architecture_trace
    assert "escalated_at" not in normal.architecture_trace and large.seen == []


@pytest.mark.parametrize("ratio", [0, -0.1, 1.1, float("nan"), True, "0.7"])
def test_invalid_escalation_ratios(ratio) -> None:
    with pytest.raises(ValueError, match="escalate_ratio"):
        CascadeArchitecture(escalate_ratio=ratio)


def test_cascade_parameters_are_part_of_contract() -> None:
    baseline = RUNNER.contract_for(_spec(), (), architecture=CascadeArchitecture())
    assert RUNNER.contract_for(_spec(), (), architecture=CascadeArchitecture(escalate_ratio=0.8)) != baseline
    assert RUNNER.contract_for(_spec(), (), architecture=CascadeArchitecture(max_rejections=1)) != baseline


def test_weighted_token_cost_counts_actual_policy_prompt_and_completion() -> None:
    first = parse_error_turn().model_copy(update={"prompt_token_ids": (1,) * 10, "sampled_token_ids": (2,) * 4})
    last = final_turn("答案").model_copy(update={"prompt_token_ids": (1,) * 20, "canonical_token_ids": (2,) * 8})
    episode, _, _ = _run([first], [last])
    assert cascade_token_cost(episode) == 14 + 28 * 2.25
    invalid = episode.model_copy(update={"turns": (episode.turns[0].model_copy(update={"policy_key": "other"}),)})
    with pytest.raises(ValueError, match="unknown policy"):
        cascade_token_cost(invalid)


def test_missing_token_data_cannot_be_reported_as_zero_cost() -> None:
    episode, _, _ = _run([final_turn("答案")], [])
    with pytest.raises(ValueError, match="token ids"):
        cascade_token_cost(episode)


def test_invalid_repair_limit_is_also_checked_by_cascade() -> None:
    with pytest.raises(ValueError, match="max_rejections"):
        CascadeArchitecture(max_rejections=-1)
