from __future__ import annotations

import asyncio

import pytest

from app.agentic_platform.domain.data_policy import TrainingCollectionAuthorization, TrainingDataPolicy
from app.agentic_platform.simulation.trajectory import ModelIORecord
from ml.agentic_platform.adapters.search_r1 import SearchR1DatasetAdapter, SearchR1DatasetError
from ml.agentic_platform.adapters.verl import VerlAgentLoopAdapter
from tests.agentic_platform.test_trajectory_export import _tokenized_transition


def test_search_r1_adapter_exports_compatible_shape_without_retokenizing() -> None:
    record = ModelIORecord.from_transition(
        _tokenized_transition().model_copy(
            update={
                "training_eligible": True,
                "data_policy": TrainingDataPolicy.synthetic_trainable(),
                "environment_snapshot_hash": "fixture-environment-hash-v1",
                "skill_catalog_hash": "fixture-skill-catalog-v1",
                "retriever_version": "fixture-retriever-v1",
            }
        )
    )
    assert record is not None

    with pytest.raises(SearchR1DatasetError, match="collection_gate_not_authorized"):
        SearchR1DatasetAdapter().export_record(record.model_dump(mode="json"))

    authorization = TrainingCollectionAuthorization.issue(
        pilot_report_hash="a" * 64,
        pilot_gate_content_hash="b" * 64,
        required_count=100,
    )
    exported = SearchR1DatasetAdapter(collection_authorization=authorization).export_record(record.model_dump(mode="json"))

    assert set(exported) == {"data_source", "prompt", "ability", "reward_model", "extra_info"}
    assert exported["extra_info"]["raw_token_ids"] == [101, 102, 103, 104, 105]
    assert exported["extra_info"]["loss_mask"] == [False, False, False, True, True]
    assert exported["reward_model"]["ground_truth"] == record.reward_facts.model_dump(mode="json")


def test_verl_adapter_uses_only_the_environment_interface() -> None:
    class FakeEnvironment:
        def __init__(self) -> None:
            self.actions: list[object] = []
            self.restored: object | None = None

        async def reset(self, scenario: object, seed: int) -> object:
            return {"scenario": scenario, "seed": seed, "state_hash": "reset-hash"}

        async def step(self, action: object) -> object:
            self.actions.append(action)
            return {"state_after_hash": f"state-{len(self.actions)}"}

        async def snapshot(self) -> object:
            return {"snapshot": "opaque"}

        async def restore(self, snapshot: object) -> None:
            self.restored = snapshot

    async def scenario() -> tuple[object, list[object], object, object]:
        environment = FakeEnvironment()
        adapter = VerlAgentLoopAdapter(environment)
        rollout = await adapter.rollout(scenario={"fixture": True}, seed=5, actions=["first", "second"])
        snapshot = await adapter.snapshot()
        await adapter.restore(snapshot)
        return rollout, environment.actions, snapshot, environment.restored

    rollout, actions, snapshot, restored = asyncio.run(scenario())

    assert actions == ["first", "second"]
    assert rollout.final_state_hash == "state-2"
    assert snapshot == restored
