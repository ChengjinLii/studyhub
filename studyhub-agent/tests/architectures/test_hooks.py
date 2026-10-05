import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from studyhub_agent.architectures.base import Accept, Continue, ReactArchitecture
from studyhub_agent.contracts.episode import Budget, Episode, EpisodeSpec, Message, Principal, Termination
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS, PromptRegistry, PromptTemplate
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.runner import EpisodeRunner
from studyhub_agent.tools.specs import select_tools
from tests.runtime.fakes import ScriptedPolicy, count_chars, count_messages, final_turn, tool_turn

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")
RUNNER = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision="test-rev", count_tokens=count_chars)


def _spec(**overrides):
    return EpisodeSpec(
        **{
            "episode_id": "ep",
            "task_id": "t",
            "user_message": "高等数学",
            "principal": Principal(principal_id="u-1001"),
            "tool_names": ("materials_search", "materials_read"),
            **overrides,
        }
    )


def test_explicit_react_preserves_default_messages_turns_and_contract() -> None:
    turns = [
        tool_turn(("materials_search", {"query": "提纲"})),
        tool_turn(("materials_read", {"material_id": 101})),
        final_turn("[101:1]"),
    ]
    baseline = RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), ScriptedPolicy(list(turns)))
    explicit = RUNNER.run(
        _spec(), ReplayEnvironment(SNAPSHOT), ScriptedPolicy(list(turns)), architecture=ReactArchitecture()
    )
    assert baseline == explicit
    assert Episode.model_validate_json(explicit.model_dump_json()) == explicit
    assert explicit.architecture == "react@1.0"


def test_default_react_matches_pinned_foundation_transcript() -> None:
    # Captured from the pre-hook runner at c209220; new provenance fields are intentionally excluded.
    episode = RUNNER.run(
        _spec(),
        ReplayEnvironment(SNAPSHOT),
        ScriptedPolicy(
            [
                tool_turn(("materials_search", {"query": "提纲"})),
                tool_turn(("materials_read", {"material_id": 101})),
                final_turn("[101:1]"),
            ]
        ),
    )
    transcript = {
        "messages": [message.model_dump(mode="json") for message in episode.messages],
        "turns": [turn.model_dump(mode="json", exclude={"policy_key", "model_id"}) for turn in episode.turns],
        "observations": [obs.model_dump(mode="json", exclude={"details"}) for obs in episode.observations],
        "termination": episode.termination,
        "failure_owner": episode.failure_owner,
        "final_answer": episode.final_answer,
        "error_detail": episode.error_detail,
    }
    encoded = json.dumps(transcript, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == "902a3a2cd6af093ce064cd8d8a22077ae60e51d739385c76cc89d9f58c3c6c4b"


class RecordingArchitecture(ReactArchitecture):
    architecture_id = "recording"

    def __init__(self):
        self.events = []

    def on_start(self, ctx):
        self.events.append("start")
        with pytest.raises(FrozenInstanceError):
            ctx.policy_key = "large"
        assert isinstance(ctx.turns, tuple) and isinstance(ctx.observations, tuple)
        return (Message(role="tool", name="runtime_feedback", content='{"notice":"start"}'),)

    def before_step(self, ctx, messages):
        self.events.append("before")
        return messages

    def select_policy(self, ctx):
        self.events.append("select")
        return "small"

    def on_final(self, ctx, turn):
        self.events.append("final")
        if len(ctx.turns) == 1:
            return Continue((Message(role="tool", name="runtime_feedback", content='{"notice":"retry"}'),), "test")
        return Accept()


def test_hooks_continue_then_accept_preserve_history_and_trace() -> None:
    architecture = RecordingArchitecture()
    policy = ScriptedPolicy([final_turn("first"), final_turn("second")])
    episode = RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=architecture)
    assert architecture.events == ["start", "before", "select", "final", "before", "select", "final"]
    assert episode.final_answer == "second" and episode.termination is Termination.FINAL_ANSWER
    assert episode.architecture_trace["continues"] == [{"turn": 0, "reason": "test"}]
    assert [m.content for m in episode.messages if m.role == "assistant"] == ["first", "second"]
    assert json.loads(policy.seen[1][-1].content)["notice"] == "retry"


def test_named_policies_record_actual_route_and_full_history() -> None:
    class SwitchArchitecture(ReactArchitecture):
        def select_policy(self, ctx):
            return "large" if ctx.turns else "small"

    small = ScriptedPolicy([tool_turn(("materials_search", {"query": "提纲"}))])
    large = ScriptedPolicy([final_turn("answer")])
    episode = RUNNER.run(
        _spec(),
        ReplayEnvironment(SNAPSHOT),
        small,
        architecture=SwitchArchitecture(),
        policies={"small": small, "large": large},
        models={"small": "4B", "large": "9B"},
        model_revisions={"small": "rev4", "large": "rev9"},
        token_counters={"small": count_chars, "large": count_chars},
    )
    assert [(t.policy_key, t.model_id) for t in episode.turns] == [("small", "4B"), ("large", "9B")]
    assert episode.models == {"small": "4B", "large": "9B"}
    assert episode.model_revisions == {"small": "rev4", "large": "rev9"}
    assert large.seen[0] == episode.messages[:-1]


def test_before_step_changes_only_sent_view_and_token_budget_uses_view() -> None:
    class ViewArchitecture(ReactArchitecture):
        def before_step(self, ctx, messages):
            return messages[:2]

    runner = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision="rev", count_tokens=count_messages)
    policy = ScriptedPolicy([tool_turn(("materials_search", {"query": "提纲"})), final_turn("answer")])
    spec = _spec(budget=Budget(max_context_tokens=13, max_new_tokens=10))
    episode = runner.run(spec, ReplayEnvironment(SNAPSHOT), policy, architecture=ViewArchitecture())
    assert episode.termination is Termination.FINAL_ANSWER
    assert len(policy.seen[1]) == 2 and len(episode.messages) == 5
    assert episode.observations[0].details["returned_material_ids"]
    assert "returned_material_ids" not in episode.messages[3].content


def test_continue_on_last_turn_cannot_escape_episode_budget() -> None:
    policy = ScriptedPolicy([final_turn("first")])
    episode = RUNNER.run(
        _spec(budget=Budget(max_turns=1)), ReplayEnvironment(SNAPSHOT), policy, architecture=RecordingArchitecture()
    )
    assert episode.termination is Termination.MAX_TURNS and episode.final_answer is None
    assert len(policy.seen) == 1


def test_unknown_policy_is_configuration_error_before_policy_execution() -> None:
    class UnknownPolicy(ReactArchitecture):
        def select_policy(self, ctx):
            return "unknown"

    policy = ScriptedPolicy([])
    with pytest.raises(ValueError, match="unknown"):
        RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=UnknownPolicy())
    assert policy.seen == []


def test_named_policy_configuration_requires_complete_model_provenance() -> None:
    policy = ScriptedPolicy([])
    with pytest.raises(ValueError, match="models"):
        RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, policies={"small": policy, "large": policy})
    assert policy.seen == []


def test_architecture_prompts_are_resolved_from_runner_registry_and_hashed() -> None:
    class PromptArchitecture(ReactArchitecture):
        prompt_keys = ("extra@1.0",)

        def on_start(self, ctx):
            return (Message(role="tool", name="runtime_feedback", content=ctx.prompts["extra@1.0"].text),)

    hashes = []
    for text in ("original", "changed"):
        registry = PromptRegistry([DEFAULT_PROMPTS.get(key) for key in DEFAULT_PROMPTS.keys()]).with_prompt(
            PromptTemplate("extra", "1.0", text)
        )
        runner = EpisodeRunner(prompts=registry, tokenizer_revision="rev", count_tokens=count_chars)
        policy = ScriptedPolicy([final_turn("answer")])
        episode = runner.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=PromptArchitecture())
        assert policy.seen[0][-1].content == text
        hashes.append(episode.contract_hash)
    assert hashes[0] != hashes[1]


def test_contract_tracks_architecture_version_and_model_revisions() -> None:
    spec = _spec()
    tools = select_tools(spec.tool_names)
    baseline = RUNNER.contract_for(spec, tools)
    architecture = RecordingArchitecture()
    changed = RUNNER.contract_for(spec, tools, architecture=architecture)
    assert changed != baseline
    architecture.version = "1.1"
    assert RUNNER.contract_for(spec, tools, architecture=architecture) != changed
    assert RUNNER.contract_for(spec, tools, models={"small": "4B"}) != baseline
    assert RUNNER.contract_for(spec, tools, model_revisions={"small": "revision-2"}) != baseline


@pytest.mark.parametrize(
    "configuration,match",
    [
        ({"policies": {}}, "initial"),
        ({"models": {"large": "9B"}}, "unknown"),
        ({"model_revisions": {"large": "revision"}}, "unknown"),
        ({"model_revisions": {"small": "different"}}, "token_counters"),
        ({"token_counters": {"unknown": count_chars}}, "unknown"),
    ],
)
def test_invalid_policy_metadata_is_rejected_before_environment_reset(configuration, match) -> None:
    class NeverReset(ReplayEnvironment):
        def reset(self, spec):
            pytest.fail("invalid config must not reset environment")

    with pytest.raises(ValueError, match=match):
        RUNNER.run(_spec(), NeverReset(SNAPSHOT), ScriptedPolicy([]), **configuration)


def test_selected_policy_uses_its_own_tokenizer_budget_counter() -> None:
    class SwitchArchitecture(ReactArchitecture):
        def select_policy(self, ctx):
            return "large" if ctx.turns else "small"

    small = ScriptedPolicy([tool_turn(("materials_search", {"query": "提纲"}))])
    large = ScriptedPolicy([])
    episode = RUNNER.run(
        _spec(),
        ReplayEnvironment(SNAPSHOT),
        small,
        architecture=SwitchArchitecture(),
        policies={"small": small, "large": large},
        models={"small": "4B", "large": "9B"},
        model_revisions={"small": "rev4", "large": "rev9"},
        token_counters={"small": count_chars, "large": lambda *_args: 100_000},
    )
    assert episode.termination is Termination.CONTEXT_BUDGET
    assert large.seen == []


def test_hook_mutations_cannot_rewrite_episode_evidence_or_messages() -> None:
    class MutatingArchitecture(ReactArchitecture):
        def before_step(self, ctx, messages):
            if ctx.observations:
                ctx.observations[0].details.clear()
                ctx.turns[0].tool_calls[0].arguments["query"] = "rewritten"
                messages[2].tool_calls[0].arguments["query"] = "rewritten"
            return messages

    policy = ScriptedPolicy([tool_turn(("materials_search", {"query": "提纲"})), final_turn("answer")])
    episode = RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=MutatingArchitecture())
    assert episode.turns[0].tool_calls[0].arguments["query"] == "提纲"
    assert episode.messages[2].tool_calls[0].arguments["query"] == "提纲"
    assert episode.observations[0].details["returned_material_ids"]
    assert policy.seen[1][2].tool_calls[0].arguments["query"] == "rewritten"


def test_returned_episode_trace_is_independent_of_hook_state() -> None:
    class RememberContext(ReactArchitecture):
        def on_final(self, ctx, turn):
            self.ctx = ctx
            ctx.trace["events"] = ["final"]
            return Accept()

    architecture = RememberContext()
    episode = RUNNER.run(
        _spec(), ReplayEnvironment(SNAPSHOT), ScriptedPolicy([final_turn("answer")]), architecture=architecture
    )
    architecture.ctx.trace["events"].append("later")
    assert episode.architecture_trace == {"events": ["final"]}


def test_invalid_final_decision_is_a_configuration_error() -> None:
    class InvalidDecision(ReactArchitecture):
        def on_final(self, ctx, turn):
            return None

    with pytest.raises(TypeError, match="Accept or Continue"):
        RUNNER.run(
            _spec(), ReplayEnvironment(SNAPSHOT), ScriptedPolicy([final_turn("answer")]), architecture=InvalidDecision()
        )
