import asyncio
from collections import Counter
from pathlib import Path

from studyhub_agent.eval import AGENTBENCH_FAMILIES, AgentBenchRunner, PolicyOutcome, load_cases
from studyhub_agent.rewards import RewardSignals
from studyhub_agent.trajectory import TrajectoryRecorder

ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT / "eval/agentbench/v1/cases.jsonl"


def test_agentbench_v1_has_balanced_fixed_cases_without_pii() -> None:
    cases = load_cases(CASES_PATH)
    raw = CASES_PATH.read_text(encoding="utf-8").casefold()

    assert len(cases) == 100
    assert Counter(case.task.family for case in cases) == Counter({family: 10 for family in AGENTBENCH_FAMILIES})
    assert all(case.task.environment_seed >= 0 for case in cases)
    assert "@" not in raw
    assert "raw_user_id" not in raw
    assert "chat_transcript" not in raw


class _DeterministicPolicy:
    async def run(self, case):
        recorder = TrajectoryRecorder(
            run_id=f"run-{case.case_id}",
            episode_id=f"episode-{case.case_id}",
            task_id=case.case_id,
            policy={"model": "fixture", "checkpoint": "none", "prompt_version": "studyhub-v2"},
        )
        recorder.record("run_started")
        answer = "回答完成"
        recorder.record("final_answer", action={"text": answer})
        recorder.record("run_finished")
        return PolicyOutcome(
            final_answer=answer,
            events=recorder.events,
            reward_signals=RewardSignals(
                final_answer=answer,
                verifier={},
                steps=3,
                max_steps=case.task.max_steps,
            ),
            valid_tool_calls=0,
            search_calls=0,
            duplicate_searches=0,
        )


def test_agentbench_runner_computes_metrics_without_writing_fake_results() -> None:
    cases = load_cases(CASES_PATH)
    metrics = asyncio.run(AgentBenchRunner(_DeterministicPolicy()).run(cases))

    assert metrics.cases == 100
    assert metrics.task_success == 1.0
    assert metrics.valid_tool_rate == 1.0
    assert metrics.average_steps == 3.0
