"""Constrained semantic action space for the isolated Router RL policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..reward import RouterRewardPolicy
from ..spec import canonical_json
from .spec import MaturityRouterState

ACTION_ROUTES = (
    "search_materials",
    "inspect_materials",
    "read_pdf_evidence",
    "read_memory",
    "synthesize_course_context",
    "final",
)
ACTION_CODES = {route: str(index) for index, route in enumerate(ACTION_ROUTES)}
CODE_ROUTES = {code: route for route, code in ACTION_CODES.items()}
ACTION_LABELS = {
    "search_materials": "检索免费资料",
    "inspect_materials": "核验候选元数据",
    "read_pdf_evidence": "读取页级证据",
    "read_memory": "读取本人学习记忆",
    "synthesize_course_context": "整合课程上下文",
    "final": "结束并回答",
}


@dataclass(frozen=True, slots=True)
class RouterActionCandidate:
    code: str
    route: str
    output: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RouterActionSpace:
    state_id: str
    oracle_route: str
    candidates: tuple[RouterActionCandidate, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(candidate.code for candidate in self.candidates)

    @property
    def routes(self) -> tuple[str, ...]:
        return tuple(candidate.route for candidate in self.candidates)

    def output_for_code(self, code: str) -> dict[str, Any]:
        for candidate in self.candidates:
            if candidate.code == code:
                return candidate.output
        raise KeyError(f"action code {code!r} is unavailable for {self.state_id}")


def build_action_space(state: MaturityRouterState) -> RouterActionSpace:
    """Build read-only candidates without using labels to mask semantic alternatives."""

    oracle_route = output_route(state.oracle_output)
    outputs: dict[str, dict[str, Any]] = {}
    for route in ACTION_ROUTES:
        candidate = _candidate_output(state, route)
        if candidate is not None:
            outputs[route] = candidate
    if oracle_route not in outputs:
        raise ValueError(f"oracle route {oracle_route} is unavailable for {state.state_id}")
    outputs[oracle_route] = dict(state.oracle_output)

    reward_policy = RouterRewardPolicy()
    candidates: list[RouterActionCandidate] = []
    for route in ACTION_ROUTES:
        output = outputs.get(route)
        if output is None:
            continue
        failed_gates = [
            name
            for name, passed in reward_policy.score(output, state).hard_gates.items()
            if not passed
        ]
        if failed_gates:
            if route == oracle_route:
                raise ValueError(
                    f"oracle action violates hard gates for {state.state_id}: {failed_gates}"
                )
            continue
        candidates.append(
            RouterActionCandidate(
                code=ACTION_CODES[route],
                route=route,
                output=output,
            )
        )
    if not candidates or oracle_route not in {candidate.route for candidate in candidates}:
        raise ValueError(f"no valid oracle action candidate for {state.state_id}")
    return RouterActionSpace(
        state_id=state.state_id,
        oracle_route=oracle_route,
        candidates=tuple(candidates),
    )


def decision_messages(state: MaturityRouterState, space: RouterActionSpace) -> list[dict[str, str]]:
    menu = "\n".join(
        f"{candidate.code}={ACTION_LABELS[candidate.route]}" for candidate in space.candidates
    )
    instruction = (
        "\n\n[OFFLINE_ROUTER_ACTION_DECISION]\n"
        "根据上面的可信状态选择下一步语义动作。安全参数由只读 action decoder 生成。\n"
        f"可选代码：\n{menu}\n"
        "只输出一个代码字符，不输出解释、JSON、空格或换行。\n"
        "动作代码："
    )
    return [
        dict(state.messages[0]),
        {
            "role": "user",
            "content": canonical_json(state.request_payload) + instruction,
        },
    ]


def action_token_ids(tokenizer: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for route, code in ACTION_CODES.items():
        token_ids = tokenizer.encode(code, add_special_tokens=False)
        if len(token_ids) != 1:
            raise ValueError(f"action code must be exactly one token: {route}={token_ids}")
        result[route] = int(token_ids[0])
    if len(set(result.values())) != len(result):
        raise ValueError("action codes must map to distinct token IDs")
    return result


def output_route(output: dict[str, Any]) -> str:
    mode = str(output.get("mode") or "")
    if mode == "final":
        return "final"
    actions = output.get("actions")
    if mode != "tools" or not isinstance(actions, list) or len(actions) != 1:
        raise ValueError("router output does not contain one semantic action")
    action = actions[0]
    if not isinstance(action, dict):
        raise TypeError("router action must be an object")
    route = str(action.get("name") or "")
    if route not in ACTION_ROUTES[:-1]:
        raise ValueError(f"unsupported router route: {route}")
    return route


def _candidate_output(state: MaturityRouterState, route: str) -> dict[str, Any] | None:
    payload = state.request_payload
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    force_final = payload.get("force_final") is True or int(budget.get("remaining_rounds") or 0) <= 0
    remaining_tools = int(budget.get("remaining_tool_calls") or 0)
    remaining_search = int(budget.get("remaining_search_calls") or 0)
    remaining_slots = int(budget.get("remaining_candidate_slots") or 0)
    rubric = state.rubric
    context = dict(payload.get("task_context") or {})

    if route == "final":
        if rubric.explicit_pages and rubric.expected_mode != "final":
            return None
        if rubric.must_refuse:
            answer = (
                "不能执行该请求。StudyHub Agent 只使用获准的只读工具和当前账号可访问的免费资料，"
                "不会绕过购买或权限、泄露访问凭据或伪造平台记录。"
            )
        else:
            terms = "、".join(rubric.answer_terms or tuple(context.get("course_terms") or []))
            subject = terms or "当前任务"
            answer = f"当前先基于已核验信息结束本轮；关于{subject}不会虚构未读取的资料事实，并给出保守的下一步建议。"
        return {
            "mode": "final",
            "task_context": context,
            "answer": answer,
            "recommendations": [],
            "evidence_sources": [],
            "followup_questions": [],
        }

    if force_final or remaining_tools <= 0 or rubric.must_refuse:
        return None
    if rubric.explicit_pages and route != "read_pdf_evidence":
        return None

    arguments: dict[str, Any]
    if route == "search_materials":
        if remaining_search <= 0 or remaining_slots <= 0:
            return None
        query_terms = list(rubric.query_terms) or list(context.get("course_terms") or [])
        query = " ".join([*map(str, query_terms[:3]), "免费资料", "复习"]).strip()
        prior = {"".join(value.casefold().split()) for value in rubric.prior_queries}
        if "".join(query.casefold().split()) in prior:
            query += " 例题"
        arguments = {
            "query": query,
            "limit": min(6, max(1, remaining_slots)),
            "filters": {},
        }
    elif route == "inspect_materials":
        material_ids = list(rubric.trusted_material_ids[:8])
        if not material_ids:
            return None
        arguments = {"material_ids": material_ids}
    elif route == "read_pdf_evidence":
        material_ids = list(rubric.trusted_material_ids[:2])
        if not material_ids:
            return None
        terms = " ".join(rubric.query_terms or tuple(context.get("course_terms") or []))
        arguments = {
            "material_ids": material_ids,
            "query": (terms + " 可核验页级证据").strip(),
            "max_pages": max(1, len(rubric.explicit_pages) or 3),
        }
        if rubric.explicit_pages:
            arguments["page_numbers"] = list(rubric.explicit_pages)
    elif route == "read_memory":
        terms = "、".join(map(str, context.get("course_terms") or [])) or "当前课程"
        arguments = {"focus": f"本人关于{terms}的学习偏好、节奏与薄弱点"}
    elif route == "synthesize_course_context":
        terms = [str(value) for value in context.get("course_terms") or []]
        arguments = {
            "task_label": f"{('、'.join(terms) or '当前课程')}学习上下文整合",
            "course_terms": terms,
            "evidence_goals": [str(context.get("exam_goal") or "形成下一步学习动作")],
            "response_preferences": ["简洁", "证据优先"],
            "constraints": ["只读", "只使用免费资料"],
        }
    else:
        raise ValueError(f"unsupported route: {route}")
    return {
        "mode": "tools",
        "progress": ACTION_LABELS[route] + "中",
        "task_context": context,
        "actions": [{"name": route, "arguments": arguments}],
    }
