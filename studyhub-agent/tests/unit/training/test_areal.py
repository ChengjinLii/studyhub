import asyncio
from pathlib import Path

from studyhub_agent.rewards import RewardResult
from studyhub_agent.runtime import TaskSpec
from studyhub_agent.trajectory import TrajectoryRecorder
from training.areal.config_schema import load_training_config
from training.areal.grouped_rollout import GroupedEpisodeCoordinator, RolloutRequest, RolloutResult
from training.areal.hermes_adapter import HermesArealAdapter, HermesRolloutOutput
from training.areal.reward_bridge import reward_to_areal
from training.areal.workflow import export_grouped_episode

ROOT = Path(__file__).resolve().parents[3]
CONFIG_ROOT = ROOT / "training/areal/configs"


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="group-case-001",
        family="rag_memory",
        difficulty="medium",
        user_request="结合资料和记忆制定复习计划",
        environment_seed=100,
        allowed_tools=["knowledge_search", "personal_memory_search"],
        max_steps=8,
        max_tool_calls=5,
    )


def test_all_training_templates_validate_without_loading_models() -> None:
    paths = sorted(CONFIG_ROOT.glob("*.yaml"))
    configs = [load_training_config(path) for path in paths]

    assert len(configs) == 5
    assert {config.algorithm.name for config in configs} == {"sft", "grpo", "opd", "kdrl", "best_of_n"}
    assert all(config.runtime.requires_cuda for config in configs)
    assert all(config.data.trajectory_schema == "studyhub.trajectory.v1" for config in configs)


def test_grouped_rollouts_share_snapshot_and_vary_only_rollout_seed(tmp_path) -> None:
    rewards = [0.9, 0.6, 0.3, 0.8]

    async def rollout(request):
        index = request.rollout_seed - request.environment_seed - 1
        recorder = TrajectoryRecorder(
            run_id=f"run-{index}",
            episode_id=f"episode-{index}",
            task_id=request.task.task_id,
            group_id=request.group_id,
            policy={"model": "fake", "checkpoint": "none", "prompt_version": "studyhub-v2"},
        )
        recorder.record("run_started", state={"rollout_seed": request.rollout_seed})
        recorder.record("reward_assigned", reward=rewards[index])
        recorder.record("run_finished", reward=rewards[index])
        reward = RewardResult(rewards[index], rewards[index], 1.0, 1.0, 1.0, 1.0, [])
        return RolloutResult(request=request, trajectory=recorder.events, reward=reward)

    group = asyncio.run(
        GroupedEpisodeCoordinator().run_group(
            _task(), group_size=4, rollout_fn=rollout, memory_snapshot_id="memory-snapshot-001"
        )
    )

    assert [item.reward.total for item in group.rollouts] == rewards
    assert len({item.request.rollout_seed for item in group.rollouts}) == 4
    assert {item.request.environment_seed for item in group.rollouts} == {100}
    assert {item.request.memory_snapshot_id for item in group.rollouts} == {"memory-snapshot-001"}
    assert {item.request.group_id for item in group.rollouts} == {group.group_id}
    outputs = export_grouped_episode(group, tmp_path)
    assert len(outputs) == 4
    assert all(path.is_file() for path in outputs)
    assert (outputs[0].parent / "group.jsonl").is_file()


def test_reward_bridge_preserves_scalar_and_components() -> None:
    reward = RewardResult(0.5, 1.0, 0.5, 1.0, 0.0, 0.5, ["duplicate_tool_call"])
    payload = reward_to_areal(reward)

    assert payload["reward"] == 0.5
    assert payload["reward_components"]["citation"] == 1.0
    assert payload["violations"] == ["duplicate_tool_call"]


def test_hermes_adapter_preserves_grouped_rollout_contract() -> None:
    seen = []

    async def hermes_runner(context):
        seen.append(context)
        recorder = TrajectoryRecorder(
            run_id="run-hermes",
            episode_id="episode-hermes",
            task_id=context.task_id,
            group_id=context.group_id,
            policy={"model": "fake", "checkpoint": "none", "prompt_version": "studyhub-v2"},
        )
        recorder.record("run_started")
        return HermesRolloutOutput(
            trajectory=recorder.events,
            reward=RewardResult(0.5, 1.0, 0.5, 1.0, 0.0, 0.5, []),
        )

    task = _task()
    request = RolloutRequest(task, "group:fixture", 100, 101, "memory-snapshot-001")
    result = asyncio.run(HermesArealAdapter(hermes_runner).run(request))

    assert result.request == request
    assert seen[0].allowed_tools == ("knowledge_search", "personal_memory_search")
    assert seen[0].rollout_seed == 101
