"""Calibrate the deterministic reward Judge against teacher-authored preferences."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .reward import RouterRewardPolicy
from .spec import RouterRLState, load_states, sha256_file


def calibrate(states: list[RouterRLState], *, maximum_cases: int = 48) -> dict[str, Any]:
    selected = _balanced_states(states, maximum_cases)
    policy = RouterRewardPolicy()
    rows: list[dict[str, Any]] = []
    correct = 0
    invariant = 0
    for state in selected:
        chosen = teacher_preferred_output(state)
        rejected = teacher_rejected_output(state)
        chosen_score = policy.score(chosen, state)
        rejected_score = policy.score(rejected, state)
        serialized = json.dumps(chosen, ensure_ascii=False, indent=2, sort_keys=False)
        reordered = json.dumps(dict(reversed(list(chosen.items()))), ensure_ascii=False, separators=(",", ":"))
        serialized_score = policy.score(serialized, state).policy_reward
        reordered_score = policy.score(reordered, state).policy_reward
        preference_correct = chosen_score.policy_reward > rejected_score.policy_reward
        sensitivity_invariant = serialized_score == reordered_score == chosen_score.policy_reward
        correct += int(preference_correct)
        invariant += int(sensitivity_invariant)
        rows.append(
            {
                "state_id": state.state_id,
                "family": state.family,
                "split": state.split,
                "teacher_preferred": chosen,
                "teacher_rejected": rejected,
                "preferred_reward": chosen_score.policy_reward,
                "rejected_reward": rejected_score.policy_reward,
                "preference_correct": preference_correct,
                "serialization_invariant": sensitivity_invariant,
            }
        )
    count = len(rows)
    return {
        "schema_version": "studyhub.agent.router_rl.judge_calibration.v1",
        "judge_type": "deterministic_programmatic_rubric",
        "teacher_label_tier": "teacher_reviewed_silver_pairwise",
        "human_gold": False,
        "external_llm_judge_used": False,
        "cases": count,
        "family_counts": dict(sorted(Counter(row["family"] for row in rows).items())),
        "pairwise_accuracy": round(correct / count, 6) if count else 0.0,
        "serialization_invariance": round(invariant / count, 6) if count else 0.0,
        "passed": count >= 20 and correct == count and invariant == count,
        "rows": rows,
        "limitations": [
            "Teacher-reviewed Silver preferences are not human gold.",
            "The deterministic Judge validates policy semantics, not open-ended pedagogical prose quality.",
            "Grounded Tutor answer quality requires a separately calibrated citation/utility Judge.",
        ],
    }


def teacher_preferred_output(state: RouterRLState) -> dict[str, Any]:
    rubric = state.rubric
    task_context = state.request_payload.get("task_context") or {}
    if rubric.expected_mode == "final":
        if rubric.must_refuse:
            answer = "不能绕过权限读取付费资料或执行写操作；StudyHub Agent 只使用只读免费资料。"
        else:
            terms = "、".join(rubric.answer_terms) or "现有信息"
            answer = f"已依据现有证据完成{terms}说明与下一步建议。"
        return {
            "mode": "final",
            "task_context": task_context,
            "answer": answer,
            "recommendations": [],
            "evidence_sources": [],
            "followup_questions": ["继续细化下一步学习安排"],
        }
    tool = rubric.expected_tools[0]
    arguments: dict[str, Any]
    if tool == "search_materials":
        arguments = {"query": " ".join(rubric.query_terms) or "免费资料 复习", "limit": 6}
    elif tool == "inspect_materials":
        arguments = {"material_ids": list(rubric.trusted_material_ids)}
    elif tool == "read_pdf_evidence":
        arguments = {
            "material_ids": list(rubric.trusted_material_ids[:2]),
            "query": " ".join(rubric.query_terms) or "关键证据",
            "max_pages": max(1, len(rubric.explicit_pages) or 3),
        }
        if rubric.explicit_pages:
            arguments["page_numbers"] = list(rubric.explicit_pages)
    elif tool == "read_memory":
        arguments = {"focus": "当前学习偏好与薄弱点"}
    else:
        arguments = {
            "task_label": "课程上下文整合",
            "course_terms": list(task_context.get("course_terms") or ["当前课程"]),
            "evidence_goals": ["形成可执行下一步"],
            "response_preferences": ["简洁", "证据优先"],
            "constraints": ["只使用免费资料"],
        }
    return {
        "mode": "tools",
        "progress": f"执行{tool}中",
        "task_context": task_context,
        "actions": [{"name": tool, "arguments": arguments}],
    }


def teacher_rejected_output(state: RouterRLState) -> dict[str, Any]:
    task_context = state.request_payload.get("task_context") or {}
    if state.rubric.expected_mode == "tools":
        return {
            "mode": "final",
            "task_context": task_context,
            "answer": "无需任何证据，直接结束。",
            "recommendations": [],
            "evidence_sources": [],
            "followup_questions": [],
        }
    return {
        "mode": "tools",
        "progress": "重复搜索中",
        "task_context": task_context,
        "actions": [{"name": "search_materials", "arguments": {"query": "无关资料", "limit": 12}}],
    }


def _balanced_states(states: list[RouterRLState], maximum: int) -> list[RouterRLState]:
    result: list[RouterRLState] = []
    by_family: dict[str, list[RouterRLState]] = {}
    for state in states:
        by_family.setdefault(state.family, []).append(state)
    while len(result) < maximum:
        added = False
        for family in sorted(by_family):
            values = by_family[family]
            if values:
                result.append(values.pop(0))
                added = True
                if len(result) >= maximum:
                    break
        if not added:
            break
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-cases", type=int, default=48)
    parser.add_argument("--fail-on-calibration", action="store_true")
    args = parser.parse_args()
    states = load_states(args.dataset, splits={"validation"})
    result = calibrate(states, maximum_cases=args.maximum_cases)
    result["dataset_path"] = str(args.dataset.resolve())
    result["dataset_sha256"] = sha256_file(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_calibration and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
