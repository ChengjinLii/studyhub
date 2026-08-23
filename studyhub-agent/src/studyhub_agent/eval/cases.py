from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studyhub_agent.runtime import TaskSpec

AGENTBENCH_VERSION = "studyhub.agentbench.v1"
AGENTBENCH_FAMILIES = (
    "rag_only",
    "web_only",
    "memory_only",
    "rag_memory",
    "rag_web",
    "rag_web_memory",
    "direct_answer",
    "insufficient_evidence",
    "permission_denied",
    "long_horizon",
)


@dataclass(frozen=True, slots=True)
class AgentBenchCase:
    schema_version: str
    case_id: str
    task: TaskSpec

    def __post_init__(self) -> None:
        if self.schema_version != AGENTBENCH_VERSION:
            raise ValueError(f"unsupported AgentBench schema: {self.schema_version}")
        if self.case_id != self.task.task_id:
            raise ValueError("case_id must equal task.task_id")
        if self.task.family not in AGENTBENCH_FAMILIES:
            raise ValueError(f"unsupported AgentBench family: {self.task.family}")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "case_id": self.case_id, "task": self.task.to_dict()}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AgentBenchCase:
        return cls(
            schema_version=str(value["schema_version"]),
            case_id=str(value["case_id"]),
            task=TaskSpec.from_dict(dict(value["task"])),
        )


def load_cases(path: str | Path) -> list[AgentBenchCase]:
    cases = [
        AgentBenchCase.from_dict(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("AgentBench case_id values must be unique")
    return cases
