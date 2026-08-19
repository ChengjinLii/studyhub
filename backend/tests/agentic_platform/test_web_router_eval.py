from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict

from app.agentic_platform.deepresearch.state import ResearchActionType, ResearchDecision
from app.agentic_platform.deepresearch.prompts import (
    ResearchPromptPurpose,
    build_research_policy_view,
    render_research_prompt,
)
from ml.agentic_platform.web_research.dataset import build_web_router_eval_cases
from ml.agentic_platform.web_research.evaluate import evaluate_policy
from ml.agentic_platform.web_research.export_sft import export_web_router_sft
from ml.agentic_platform.web_research.local_policy import (
    extract_first_json_object,
    parse_research_decision,
)
from ml.agentic_platform.web_research.policy import DeterministicWebRouterPolicy
from ml.agentic_platform.web_research.rl_environment import (
    FrozenWebResearchEnvironment,
    build_web_rl_pilot_scenarios,
    candidate_research_decisions,
)
from ml.agentic_platform.web_research.search_r1_grpo import (
    SEARCH_R1_REFERENCE_COMMIT,
    SearchR1Trajectory,
    SearchR1Turn,
    assign_group_outcome_advantages,
    search_r1_outcome_reward,
)
from ml.agentic_platform.web_research.spec import evaluate_predictions, gate_evaluation


def test_web_router_suite_is_frozen_balanced_and_isolated() -> None:
    first = build_web_router_eval_cases()
    second = build_web_router_eval_cases()

    assert len(first) == 100
    assert Counter(case.split for case in first) == {"train": 60, "validation": 20, "test": 20}
    by_family: dict[str, set[str]] = defaultdict(set)
    for case in first:
        by_family[case.family].add(case.split)
        assert all(value is False for value in case.to_dict()["isolation"].values())
    assert len(by_family) == 8
    assert all(splits == {"train", "validation", "test"} for splits in by_family.values())
    assert [case.content_hash for case in first] == [case.content_hash for case in second]


def test_deterministic_web_router_baseline_passes_the_frozen_gate() -> None:
    cases = build_web_router_eval_cases()
    policy = DeterministicWebRouterPolicy()
    decisions = [asyncio.run(policy.decide(case.state)) for case in cases]

    scores, summary = evaluate_predictions(cases, decisions)
    gate = gate_evaluation(summary)

    assert all(score.passed for score in scores)
    assert summary["case_pass_rate"] == 1.0
    assert summary["required_web_recall"] == 1.0
    assert summary["unnecessary_web_rate"] == 0.0
    assert summary["sensitive_query_safety_rate"] == 1.0
    assert gate["passed"] is True
    assert gate["blockers"] == []


def test_gate_rejects_a_policy_that_routes_every_case_to_web_search() -> None:
    cases = build_web_router_eval_cases()
    decisions = [
        ResearchDecision(
            action_type=ResearchActionType.SEARCH_WEB,
            rationale_summary="Unsafe all-Web baseline.",
            query=case.state.research_question,
        )
        for case in cases
    ]

    _scores, summary = evaluate_predictions(cases, decisions)
    gate = gate_evaluation(summary)

    assert gate["passed"] is False
    assert summary["unnecessary_web_rate"] > 0.0
    assert summary["sensitive_query_safety_rate"] == 0.0
    assert "sensitive_query_safety" in gate["blockers"]
    assert "unnecessary_web" in gate["blockers"]


def test_gate_counts_invalid_structured_output_instead_of_aborting() -> None:
    cases = build_web_router_eval_cases()
    policy = DeterministicWebRouterPolicy()
    decisions: list[ResearchDecision | None] = [asyncio.run(policy.decide(case.state)) for case in cases]
    decisions[0] = None

    scores, summary = evaluate_predictions(cases, decisions)
    gate = gate_evaluation(summary)

    assert scores[0].predicted_action == "invalid_output"
    assert scores[0].structured_output_valid is False
    assert summary["structured_output_rate"] == 0.99
    assert gate["passed"] is False
    assert "structured_output" in gate["blockers"]


def test_free_generation_is_bounded_to_first_complete_json_action() -> None:
    expected = ResearchDecision(
        action_type=ResearchActionType.FINALIZE,
        rationale_summary="Enough evidence is available.",
    )
    raw = expected.model_dump_json() + "user\nrepeat the prompt"

    bounded = extract_first_json_object(raw)
    decision, error = parse_research_decision(raw)

    assert bounded == expected.model_dump_json()
    assert decision == expected
    assert error is None


def test_policy_exception_is_recorded_as_one_invalid_prediction() -> None:
    class BrokenPolicy:
        async def decide(self, _state):
            raise ValueError("fixture failure")

    case = build_web_router_eval_cases()[0]
    rows, summary, gate = asyncio.run(evaluate_policy(BrokenPolicy(), [case]))

    assert rows[0]["decision"] is None
    assert rows[0]["prediction_error_type"] == "ValueError"
    assert summary["prediction_error_distribution"] == {"ValueError": 1}
    assert gate["passed"] is False


def test_web_router_sft_export_uses_only_frozen_split_records(tmp_path) -> None:
    dataset_dir = tmp_path / "llamafactory"

    manifest = export_web_router_sft(dataset_dir)

    assert manifest["counts"] == {"train": 60, "validation": 20, "test": 20}
    assert all(value is False for value in manifest["isolation"].values())
    train_rows = [json.loads(line) for line in (dataset_dir / "web_router_train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(train_rows) == 60
    assert all(row["case_id"].split("-")[-1] <= "009" for row in train_rows)
    assert all(row["messages"][-1]["role"] == "assistant" for row in train_rows)
    assert all(ResearchDecision.model_validate_json(row["messages"][-1]["content"]) for row in train_rows)


def test_web_router_sft_export_can_add_multiturn_transition_states(tmp_path) -> None:
    manifest = export_web_router_sft(
        tmp_path / "multiturn",
        include_multi_turn=True,
    )

    assert manifest["counts"] == {"train": 186, "validation": 62, "test": 62}
    assert manifest["multi_turn_transition_examples"] is True
    assert sum(count for family, count in manifest["family_counts"]["train"].items() if family.startswith("trajectory_")) == 126


def test_web_rl_pilot_scenarios_are_split_and_complete_multi_turn() -> None:
    scenarios = build_web_rl_pilot_scenarios()

    assert Counter(item.split for item in scenarios) == {
        "train": 45,
        "validation": 15,
        "test": 15,
    }
    assert len({item.family for item in scenarios}) == 5

    async def run_scenario(scenario) -> None:
        policy = DeterministicWebRouterPolicy()
        environment = FrozenWebResearchEnvironment()
        state = await environment.reset(scenario, seed=7703)
        result = None
        for _step in scenario.transitions:
            decision = await policy.decide(state)
            available = candidate_research_decisions(state)
            assert decision.action_type in {item.action_type for item in available}
            result = await environment.step(decision)
            assert result.action_correct is True
            state = result.state
        assert result is not None
        assert result.done is True
        assert result.completed is True

    for scenario in scenarios:
        asyncio.run(run_scenario(scenario))


def test_policy_view_marks_read_and_unread_sources_for_cross_source_routing() -> None:
    scenario = next(item for item in build_web_rl_pilot_scenarios() if item.family == "cross_source" and item.split == "validation")
    environment = FrozenWebResearchEnvironment()
    policy = DeterministicWebRouterPolicy()
    state = asyncio.run(environment.reset(scenario, seed=7703))
    search = asyncio.run(policy.decide(state))
    state = asyncio.run(environment.step(search)).state

    view = build_research_policy_view(
        state,
        purpose=ResearchPromptPurpose.POLICY,
        token_budget=12_000,
    )
    rendered = render_research_prompt(view, ResearchDecision).rendered_prompt

    assert [source["has_evidence"] for source in view.sources] == [True, False]
    assert "has_evidence=false" in rendered
    assert "copy its source_id exactly" in rendered


def test_web_rl_environment_terminates_on_wrong_action() -> None:
    scenario = build_web_rl_pilot_scenarios()[0]
    environment = FrozenWebResearchEnvironment()
    asyncio.run(environment.reset(scenario, seed=1))

    result = asyncio.run(
        environment.step(
            ResearchDecision(
                action_type=ResearchActionType.ABORT,
                rationale_summary="Wrong fixture action.",
            )
        )
    )

    assert result.done is True
    assert result.completed is False
    assert result.action_correct is False
    assert result.reward == -0.5


def test_search_r1_outcome_reward_and_group_advantage_are_trajectory_level() -> None:
    assert len(SEARCH_R1_REFERENCE_COMMIT) == 40

    def trajectory(index: int, *, completed: bool, valid: bool) -> SearchR1Trajectory:
        turn = SearchR1Turn(
            turn_index=0,
            state_hash=f"state-{index}",
            prompt="masked observation prompt",
            prompt_tokens=7,
            response_token_ids=[1, 2, 3],
            raw_generated="{}",
            structured_output_valid=valid,
            prediction_error_type=None if valid else "invalid_json",
            action_type="finalize" if valid else None,
            transition_valid=completed,
            observation_type="terminal",
        )
        item = SearchR1Trajectory(
            scenario_id="scenario",
            split="train",
            family="current_web",
            rollout_index=index,
            turns=[turn],
            completed=completed,
            reward=0.0,
        )
        item.reward = search_r1_outcome_reward(item)
        return item

    group = [
        trajectory(0, completed=True, valid=True),
        trajectory(1, completed=False, valid=True),
        trajectory(2, completed=False, valid=False),
        trajectory(3, completed=False, valid=False),
        trajectory(4, completed=False, valid=False),
    ]
    assign_group_outcome_advantages(group)

    assert [item.reward for item in group] == [1.0, 0.2, 0.0, 0.0, 0.0]
    assert group[0].advantage > group[1].advantage > group[2].advantage
    assert abs(sum(item.advantage for item in group)) < 1e-5
    assert all(item.turns[0].advantage == item.advantage for item in group)
