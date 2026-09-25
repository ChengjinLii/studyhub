from __future__ import annotations

from studyhub_agent.contracts.episode import Episode, FailureOwner
from studyhub_agent.graders.base import GradeResult, TaskSpec


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split())


class ExactMatchGrader:
    """Test grader: normalized exact match plus required-tool usage."""

    def grade(self, episode: Episode, task: TaskSpec) -> GradeResult:
        # From observations (calls actually executed), not turns (calls attempted): a tool call can
        # appear in episode.turns without a matching observation, e.g. when the runner cuts a turn
        # off at the tool budget before executing any of its calls (see runtime.runner).
        used = {observation.name for observation in episode.observations}
        matches = task.expected_final is None or _normalize(
            episode.final_answer
        ) == _normalize(task.expected_final)
        gates = {
            "final_answer_present": bool(_normalize(episode.final_answer)),
            "required_tools_used": set(task.required_tools) <= used,
            "answer_matches": matches,
        }
        strict = all(gates.values())
        if episode.failure_owner in {FailureOwner.INFRA, FailureOwner.ENV}:
            owner = episode.failure_owner
        else:
            owner = FailureOwner.NONE if strict else FailureOwner.MODEL
        evidence = tuple(f"{gate}=false" for gate, ok in gates.items() if not ok)
        return GradeResult(
            strict_pass=strict and owner is FailureOwner.NONE,
            hard_gates=gates,
            scores={"answer_match": 1.0 if matches else 0.0},
            failure_owner=owner,
            evidence=evidence,
        )
