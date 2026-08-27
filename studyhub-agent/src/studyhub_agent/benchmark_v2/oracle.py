from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.development_evaluator import evaluate_development
from studyhub_agent.benchmark_v2.environment import ReplayableAgentEnvironmentV2
from studyhub_agent.benchmark_v2.metrics import EvaluationResult
from studyhub_agent.benchmark_v2.schema import load_jsonl


def _first(group: list[Any]) -> str:
    return str(group[0]) if group else ""


def oracle_answer(grader: dict[str, Any]) -> str:
    outcome = dict(grader.get("outcome", {}))
    if outcome.get("mode") == "abstain":
        return "证据不足，现有可访问来源无法确认。"
    sentences: list[str] = []
    covered: set[str] = set()
    for claim in grader.get("claims", []):
        values = [_first(group) for group in claim.get("acceptable_semantic_answers", [])]
        values = [value for value in values if value]
        covered.update(value.casefold() for value in values)
        sentence = "; ".join(values)
        if claim.get("citation_required", True):
            sentence += f" [{claim['support_source_ids'][0]}]"
        sentences.append(sentence + ".")
    remaining = [
        _first(group)
        for group in outcome.get("acceptable_answers", [])
        if _first(group) and _first(group).casefold() not in covered
    ]
    if remaining:
        sentences.append("; ".join(remaining) + ".")
    return " ".join(sentences) or "任务已按要求完成。"


def _set_path(state: dict[str, Any], path: str, value: Any) -> None:
    current = state
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def oracle_state_from_assertions(environment: dict[str, Any], grader: dict[str, Any]) -> dict[str, Any]:
    state = json.loads(json.dumps(environment.get("initial_state", {}), ensure_ascii=False))
    for assertion in grader.get("outcome", {}).get("state_assertions", []):
        path = str(assertion["path"])
        operator = str(assertion.get("operator", "equals"))
        expected = assertion.get("value")
        if operator in {"equals", "at_least"}:
            _set_path(state, path, expected)
        elif operator == "contains":
            _set_path(state, path, [expected])
        elif operator == "not_contains":
            _set_path(state, path, {})
    return state


class ScriptedOracle:
    """Hidden deterministic solver used only to prove fixture reachability."""

    def __init__(self, *, environment: dict[str, Any], grader: dict[str, Any], root: Path) -> None:
        self.environment_record = environment
        self.grader = grader
        self.environment = ReplayableAgentEnvironmentV2(environment, root=root)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return json.loads(await self.environment.execute(name, arguments))

    def _document(self, source_id: str) -> dict[str, Any] | None:
        return self.environment._documents.get(source_id)  # noqa: SLF001 - oracle inspects the hidden fixture

    def _web_page(self, source_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in self.environment_record.get("web_pages", []) if str(row.get("source_id")) == source_id),
            None,
        )

    async def _discover_and_read_document(self, source_id: str, query: str) -> None:
        if source_id in self.environment.trace.read_source_ids:
            return
        document = self._document(source_id)
        if document is None:
            raise RuntimeError(f"oracle document missing: {source_id}")
        if source_id in self.environment.trace.discovered_source_ids:
            result = await self.call("knowledge_read", {"source_id": source_id})
            if not result.get("ok"):
                raise RuntimeError(f"oracle could not read discovered document {source_id}: {result}")
            return
        attempts = [query, str(document.get("title", "")), str(document.get("text", ""))[:180]]
        for attempt in attempts:
            if not attempt.strip():
                continue
            fingerprint = json.dumps(
                ["knowledge_search", {"limit": 12, "query": attempt}],
                ensure_ascii=False,
                sort_keys=True,
            )
            prior = {
                json.dumps(
                    [call.get("name"), call.get("arguments", {})],
                    ensure_ascii=False,
                    sort_keys=True,
                )
                for call in self.environment.trace.tool_calls
            }
            if fingerprint in prior:
                continue
            await self.call("knowledge_search", {"query": attempt, "limit": 12})
            if source_id in self.environment.trace.discovered_source_ids:
                break
        if source_id not in self.environment.trace.discovered_source_ids and document.get("material_id") is not None:
            await self.call("knowledge_browse", {"material_id": int(document["material_id"]), "limit": 12})
        if source_id not in self.environment.trace.discovered_source_ids:
            raise RuntimeError(f"oracle could not discover document: {source_id}")
        result = await self.call("knowledge_read", {"source_id": source_id})
        if not result.get("ok"):
            raise RuntimeError(f"oracle could not read document {source_id}: {result}")

    async def _discover_and_fetch_web(self, source_id: str, query: str) -> None:
        if source_id in self.environment.trace.read_source_ids:
            return
        page = self._web_page(source_id)
        if page is None:
            raise RuntimeError(f"oracle web page missing: {source_id}")
        await self.call("web_search", {"query": query or str(page.get("title", "")), "limit": 12})
        result = await self.call("web_fetch", {"url": str(page["url"])})
        if not result.get("ok"):
            raise RuntimeError(f"oracle could not fetch web page {source_id}: {result}")

    async def _exercise_memory(self, source_id: str, query: str) -> None:
        personal = {str(row.get("source_id")) for row in self.environment_record.get("personal_memories", [])}
        collective = {str(row.get("source_id")) for row in self.environment_record.get("collective_memories", [])}
        if source_id in personal:
            await self.call("personal_memory_search", {"query": query or "current preference", "limit": 12})
        elif source_id in collective:
            row = next(
                row
                for row in self.environment_record.get("collective_memories", [])
                if str(row.get("source_id")) == source_id
            )
            await self.call(
                "collective_memory_search",
                {
                    "query": query or str(row.get("content", ""))[:120],
                    "course": str(row.get("course", "")),
                    "limit": 12,
                },
            )

    async def _run_long_chain(self) -> None:
        chain = [row for row in self.environment._documents.values() if row.get("unlock_after_source_ids")]  # noqa: SLF001
        roots = [
            row
            for row in self.environment._documents.values()  # noqa: SLF001
            if str(row.get("source_id", "")).startswith("chain-source:") and not row.get("unlock_after_source_ids")
        ]
        if not roots and not chain:
            return
        pending = roots + sorted(chain, key=lambda row: len(row.get("unlock_after_source_ids", [])))
        for row in pending:
            text = str(row.get("text", ""))
            match = re.search(r"Lookup key ([^\s.]+)", text)
            await self._discover_and_read_document(
                str(row["source_id"]), match.group(1) if match else str(row["title"])
            )

    async def _run_process_contract(self) -> None:
        process = self.grader.get("evaluation_contract", {}).get("process_constraints", {})
        mode = str(process.get("mode", "open_path"))
        if mode == "query_reformulation":
            await self.call("knowledge_search", {"query": "CPS curriculum abbreviation", "limit": 5})
            for bridge_id in map(str, process.get("bridge_source_ids", [])):
                await self.call("knowledge_read", {"source_id": bridge_id})
            await self.call(
                "knowledge_search",
                {
                    "query": "Communication Principles",
                    "limit": 12,
                },
            )
        elif mode == "permission_recovery":
            private = next(
                row
                for row in self.environment._documents.values()  # noqa: SLF001
                if str(row.get("access_scope")) in {"private", "paid"}
            )
            await self.call("knowledge_read", {"source_id": str(private["source_id"])})
        elif mode == "failure_recovery":
            await self.call("knowledge_search", {"query": "initial transient probe", "limit": 5})
        await self._run_long_chain()
        required = list(map(str, process.get("required_tools", [])))
        if "learning_profile_get" in required:
            await self.call("learning_profile_get", {})
        if "personal_memory_search" in required:
            await self.call("personal_memory_search", {"query": "current technical focus", "limit": 12})

    async def _satisfy_claim_sources(self) -> None:
        for claim in self.grader.get("claims", []):
            query = " ".join(_first(group) for group in claim.get("acceptable_semantic_answers", []))
            for source_id in map(str, claim.get("support_source_ids", [])):
                if self._document(source_id) is not None:
                    await self._discover_and_read_document(source_id, query)
                elif self._web_page(source_id) is not None:
                    await self._discover_and_fetch_web(source_id, query)
                else:
                    await self._exercise_memory(source_id, query)

    async def _satisfy_memory_abstention(self) -> None:
        forbidden = set(
            map(
                str,
                self.grader.get("evaluation_contract", {}).get("process_constraints", {}).get("forbidden_tools", []),
            )
        )
        if (
            not self.grader.get("claims")
            and "memory" in str(self.grader.get("capability_id"))
            and not forbidden.intersection(self.environment_record.get("available_tools", []))
        ):
            if "personal_memory_search" in self.environment_record.get("available_tools", []):
                await self.call("personal_memory_search", {"query": "requested preference", "limit": 12})
            elif "collective_memory_search" in self.environment_record.get("available_tools", []):
                await self.call("collective_memory_search", {"query": "requested pattern", "course": "", "limit": 12})

    async def _satisfy_state(self) -> None:
        assertions = list(self.grader.get("outcome", {}).get("state_assertions", []))
        if not assertions:
            return
        plans: dict[str, dict[str, Any]] = {}
        for assertion in assertions:
            parts = str(assertion["path"]).split(".")
            if parts[0] == "study_plans" and len(parts) >= 3:
                item = plans.setdefault(parts[1], {"topic": parts[1], "weekly_minutes": 1, "resource_ids": []})
                if parts[2] == "weekly_minutes":
                    item["weekly_minutes"] = int(assertion["value"])
                elif parts[2] == "resource_ids":
                    item["resource_ids"].append(int(assertion["value"]))
        for plan in plans.values():
            await self.call("study_plan_update", plan)
        for assertion in assertions:
            parts = str(assertion["path"]).split(".")
            if parts[0] == "bookmarks" and assertion.get("operator") == "contains":
                await self.call("material_bookmark_add", {"material_id": int(assertion["value"])})
            elif parts[0] == "progress" and len(parts) >= 3 and parts[2] == "status":
                await self.call(
                    "learning_progress_record",
                    {"topic": parts[1], "status": str(assertion["value"])},
                )

    async def solve(self) -> tuple[str, dict[str, Any], dict[str, Any], EvaluationResult]:
        await self._run_process_contract()
        await self._satisfy_claim_sources()
        await self._satisfy_memory_abstention()
        await self._satisfy_state()
        answer = oracle_answer(self.grader)
        trace = self.environment.trace.to_dict()
        state = self.environment.state_snapshot()
        result = evaluate_development(final_answer=answer, trace=trace, final_state=state, grader=self.grader)
        return answer, trace, state, result


def load_hidden_records(root: Path, split: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    tasks_path = root / "tasks" / f"{split}.jsonl"
    if split in {"regression", "development", "calibration_challenge"}:
        public_root = root.parents[2] / "benchmarks/studyhub-agent-v2"
        tasks_path = public_root / split / "tasks.jsonl"
    tasks = load_jsonl(tasks_path)
    environments = {str(row["task_id"]): row for row in load_jsonl(root / "environments" / f"{split}.jsonl")}
    graders = {str(row["task_id"]): row for row in load_jsonl(root / "graders" / f"{split}.jsonl")}
    return tasks, environments, graders
