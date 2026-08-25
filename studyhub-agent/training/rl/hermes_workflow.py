from __future__ import annotations

import asyncio
import fcntl
import functools
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from training.rl.frozen_environment import FrozenTaskEnvironment
from training.rl.reward_v2 import RewardV2Result, evaluate_reward_v2

SYSTEM_PROMPT = """You are StudyHub Agent in an isolated training environment.
Use only the tools exposed for this task. Never access the network, filesystem, shell,
credentials, or production StudyHub services. For corpus tasks, search before reading,
read the necessary evidence, and cite every used source as [source_id]. Stop when the
answer is supported; do not invent observations or citations."""


@functools.lru_cache(maxsize=8)
def _load_verifier_store(verifier_root: Path) -> dict[str, dict[str, Any]]:
    verifiers = {}
    for path in sorted(verifier_root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                verifier_id = str(row["verifier_id"])
                if verifier_id in verifiers:
                    raise ValueError(f"duplicate verifier_id: {verifier_id}")
                verifiers[verifier_id] = row
    if not verifiers:
        raise FileNotFoundError(f"no verifier JSONL files under {verifier_root}")
    return verifiers


class StudyHubHermesWorkflow:
    """AReaL-compatible workflow that keeps Hermes as the rollout harness."""

    def __init__(
        self,
        *,
        environment_root: str,
        verifier_root: str,
        hermes_checkout: str,
        reward_artifact_root: str,
        max_turns: int = 10,
        max_tokens: int = 1536,
        max_completion_tokens: int | None = None,
        temperature: float = 1.0,
        top_p: float = 1.0,
        **_: Any,
    ) -> None:
        self.environment_root = Path(environment_root).resolve()
        self.verifier_root = Path(verifier_root).resolve()
        self.hermes_checkout = Path(hermes_checkout).resolve()
        self.reward_artifact_root = Path(reward_artifact_root).resolve()
        self.max_turns = max_turns
        self.max_tokens = max_completion_tokens or max_tokens
        self.temperature = temperature
        self.top_p = top_p
        _load_verifier_store(self.verifier_root)

    def _load_hermes(self):
        checkout = str(self.hermes_checkout)
        if checkout not in sys.path:
            sys.path.insert(0, checkout)
        from run_agent import AIAgent
        from tools.registry import registry

        return AIAgent, registry

    async def run(self, data: dict[str, Any], **extra_kwargs: Any) -> float:
        task_id = str(data["task_id"])
        metadata = dict(data.get("metadata", {}))
        if data.get("verifier"):
            raise RuntimeError(f"public task {task_id} contains verifier data")
        verifier_id = str(metadata.get("verifier_id", ""))
        verifier = _load_verifier_store(self.verifier_root).get(verifier_id)
        if verifier is None:
            raise KeyError(f"hidden verifier not found: {verifier_id}")
        max_tool_calls = int(data["max_tool_calls"])
        environment = FrozenTaskEnvironment.from_root(
            self.environment_root,
            task_id,
            max_tool_calls=max_tool_calls,
        )
        base_url = extra_kwargs.get("base_url") or os.getenv("OPENAI_BASE_URL")
        api_key = extra_kwargs.get("api_key") or os.getenv("OPENAI_API_KEY")
        if not base_url or not api_key:
            raise RuntimeError("AReaL did not provide the rollout gateway URL and session API key")

        AIAgent, registry = self._load_hermes()
        toolset = f"studyhub-rl-{task_id}"
        installed = []
        for schema in environment.tool_schemas:
            name = schema["name"]

            async def handler(arguments: dict[str, Any], _name: str = name, **_kwargs: Any) -> str:
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    arguments = {}
                return await environment.execute(_name, arguments)

            registry.register(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                is_async=True,
                description=schema["description"],
                max_result_size_chars=12_000,
            )
            if registry.get_entry(name) is None:
                raise RuntimeError(f"Hermes rejected isolated tool registration: {name}")
            installed.append(name)

        try:
            agent = AIAgent(
                base_url=str(base_url),
                api_key=str(api_key),
                provider="custom",
                api_mode="chat_completions",
                model="default",
                max_iterations=min(self.max_turns, int(data["max_steps"])),
                enabled_toolsets=[toolset],
                save_trajectories=False,
                quiet_mode=True,
                tool_progress_mode="off",
                ephemeral_system_prompt=SYSTEM_PROMPT,
                session_id=f"{task_id}-{uuid.uuid4().hex[:12]}",
                max_tokens=self.max_tokens,
                request_overrides={"temperature": self.temperature, "top_p": self.top_p},
                skip_context_files=True,
                load_soul_identity=False,
                skip_memory=True,
                skip_background_review=True,
                session_db=None,
                checkpoints_enabled=False,
            )
            agent._disable_streaming = True
            final_answer = str(await asyncio.to_thread(agent.chat, str(data["user_request"])))
        finally:
            for name in installed:
                registry.deregister(name)

        result = evaluate_reward_v2(
            final_answer=final_answer,
            trace=environment.trace,
            verifier=verifier,
            max_tool_calls=max_tool_calls,
        )
        self._record_reward(task_id, final_answer, environment, result)
        return result.total

    def _record_reward(
        self,
        task_id: str,
        final_answer: str,
        environment: FrozenTaskEnvironment,
        result: RewardV2Result,
    ) -> None:
        self.reward_artifact_root.mkdir(parents=True, exist_ok=True)
        path = self.reward_artifact_root / "reward-v2.jsonl"
        row = {
            "task_id": task_id,
            "final_answer_sha256": __import__("hashlib").sha256(final_answer.encode()).hexdigest(),
            "tool_calls": len(environment.trace.tool_calls),
            "read_sources": sorted(environment.trace.read_source_ids),
            "reward": result.to_dict(),
        }
        with path.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
