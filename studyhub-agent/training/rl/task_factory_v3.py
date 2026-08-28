from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from training.rl.dataset_v3 import (
    PUBLIC_TASK_SCHEMA_VERSION,
    budget_for,
    validate_hidden_verifier,
    validate_public_task,
)
from training.rl.environment_v3 import ENVIRONMENT_V3_SCHEMA

_COURSES = (
    "信号与系统",
    "通信原理",
    "数字电路",
    "大学物理",
    "线性代数",
    "概率论",
    "数据结构",
    "计算机网络",
    "操作系统",
    "模拟电路",
    "自动控制",
    "高等数学",
)
_PRINCIPLES = (
    "先核对适用条件，再代入公式",
    "先画出信号分段，再处理边界",
    "先建立状态转移，再检查终止条件",
    "先区分定义域，再比较极限",
    "先确认参考方向，再统一符号",
    "先定位主结论，再回查例外条件",
    "先验证量纲，再进行数值计算",
    "先拆分子问题，再合并证据",
)
_PREFERENCES = (
    "先看概念图，再做两道例题",
    "先复盘错题，再补公式条件",
    "每次学习四十分钟并保留十分钟自测",
    "优先阅读短讲义，再查完整教材",
    "先独立作答，再对照解析",
    "按章节顺序复习，不按下载热度排序",
)
_OFFICIAL_VALUES = (
    "提交截止为 2026-10-18 18:00",
    "当前版本为 3.2",
    "报名窗口在 2026-11-03 关闭",
    "本轮要求至少完成四次练习",
    "最新通知要求使用新版模板",
    "本学期考核权重为百分之三十",
)


def stable_digest(value: str, *, salt: str = "agent-rl-v3") -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def clean(value: Any) -> str:
    return re.sub(r"[ \t]+", " ", str(value or "").replace("\x00", " ")).strip()


def _normalize_external_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_external_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _normalize_external_schema(item) for key, item in value.items()}
    aliases = {"dict": "object", "float": "number", "int": "integer", "bool": "boolean"}
    kind = result.get("type")
    if isinstance(kind, str) and kind in aliases:
        result["type"] = aliases[kind]
    elif kind is not None and not isinstance(kind, str):
        if isinstance(result.get("properties"), dict):
            result["type"] = "object"
        else:
            result.pop("type", None)
    if "default" in result:
        default = result["default"]
        kind = result.get("type")
        valid = (
            kind not in {"string", "integer", "number", "boolean", "array", "object"}
            or (kind == "string" and isinstance(default, str))
            or (kind == "integer" and isinstance(default, int) and not isinstance(default, bool))
            or (kind == "number" and isinstance(default, (int, float)) and not isinstance(default, bool))
            or (kind == "boolean" and isinstance(default, bool))
            or (kind == "array" and isinstance(default, list))
            or (kind == "object" and isinstance(default, dict))
        )
        if not valid:
            result.pop("default", None)
    return result


def task_id(source: str, source_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", source.casefold()).strip("-")[:24]
    return f"rlv3-{slug}-{stable_digest(f'{source}:{source_id}')[:18]}"


def _hard_constraints(tier: str, *, citations: bool = False) -> dict[str, Any]:
    budget = budget_for(tier)
    return {
        "max_tool_calls": budget["max_tool_calls"],
        "respect_acl": True,
        "no_cross_user_memory": True,
        "citations_must_be_observed": citations,
        "hidden_oracle_access": False,
    }


def _public_task(
    *,
    task: str,
    goal: str,
    family: str,
    source_dataset: str,
    source_id: str,
    source_group_id: str,
    tools: list[str],
    tier: str,
    initial_state: dict[str, Any],
    citations: bool,
    origin: str,
    template_id: str,
) -> dict[str, Any]:
    value = {
        "schema_version": PUBLIC_TASK_SCHEMA_VERSION,
        "task_id": task,
        "goal": clean(goal),
        "initial_state": copy.deepcopy(initial_state),
        "available_tools": list(tools),
        "hard_constraints": _hard_constraints(tier, citations=citations),
        "environment_id": task,
        "budget_tier": tier,
        "metadata": {
            "family": family,
            "source_dataset": source_dataset,
            "source_id": source_id,
            "source_group_id": source_group_id,
            "origin": origin,
            "template_id": template_id,
            "verifier_id": task,
            "split": "candidate",
            "oracle_fields_exposed": False,
        },
    }
    validate_public_task(value)
    return value


def _verifier(
    *,
    task: str,
    family: str,
    objective: dict[str, Any],
    claims: list[dict[str, Any]] | None = None,
    semantic_requirements: list[dict[str, Any]] | None = None,
    max_tool_calls: int,
    process: dict[str, Any] | None = None,
    extra_constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    constraints = {"max_tool_calls": max_tool_calls}
    constraints.update(extra_constraints or {})
    value = {
        "schema_version": "studyhub.reward-verifier.v3",
        "verifier_id": task,
        "task_id": task,
        "family": family,
        "hard_constraints": constraints,
        "objective": objective,
        "claims": claims or [],
        "semantic_rubric": {"requirements": semantic_requirements or []},
        "process": process or {"max_reasonable_tool_calls": max_tool_calls},
        "thresholds": {"objective": 0.99, "grounding": 0.99, "semantic": 0.75},
    }
    validate_hidden_verifier(value)
    return value


def _replay_environment(
    *,
    task: str,
    tools: list[str],
    tier: str,
    identity: dict[str, Any] | None = None,
    initial_state: dict[str, Any] | None = None,
    documents: list[dict[str, Any]] | None = None,
    web_pages: list[dict[str, Any]] | None = None,
    personal_memories: list[dict[str, Any]] | None = None,
    collective_memories: list[dict[str, Any]] | None = None,
    failure_schedule: list[dict[str, Any]] | None = None,
    direct_read_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ENVIRONMENT_V3_SCHEMA,
        "environment_kind": "replay",
        "task_id": task,
        "identity": identity or {"user_id": f"sim-{task[-10:]}"},
        "available_tools": tools,
        "max_tool_calls": budget_for(tier)["max_tool_calls"],
        "initial_state": copy.deepcopy(initial_state or {}),
        "inline_documents": copy.deepcopy(documents or []),
        "web_pages": copy.deepcopy(web_pages or []),
        "personal_memories": copy.deepcopy(personal_memories or []),
        "collective_memories": copy.deepcopy(collective_memories or []),
        "failure_schedule": copy.deepcopy(failure_schedule or []),
        "direct_read_allowlist": list(direct_read_allowlist or []),
        "snapshot_at": "2026-08-01T00:00:00Z",
    }


def _bundle(
    task: dict[str, Any],
    environment: dict[str, Any],
    verifier: dict[str, Any],
    actions: list[dict[str, Any]],
    final_answer: str,
    *,
    alternative_actions: list[dict[str, Any]] | None = None,
    alternative_final_answer: str | None = None,
) -> dict[str, Any]:
    return {
        "task": task,
        "environment": environment,
        "verifier": verifier,
        "witness": {
            "schema_version": "studyhub.rl-solvability-witness.v3",
            "task_id": task["task_id"],
            "actions": actions,
            "final_answer": final_answer,
            "alternative_actions": alternative_actions or [],
            "alternative_final_answer": alternative_final_answer or "",
            "rollout_visible": False,
            "reward_uses_path_equality": False,
        },
    }


def _topic(index: int) -> tuple[str, str, str]:
    course = _COURSES[index % len(_COURSES)]
    code = f"M{index:05d}"
    return course, f"{course}{code}模块", code


def custom_rag(index: int) -> dict[str, Any]:
    course, topic, code = _topic(index)
    principle = _PRINCIPLES[index % len(_PRINCIPLES)]
    source_a = f"train-rag-{stable_digest(f'{index}:a')[:14]}"
    source_b = f"train-rag-{stable_digest(f'{index}:b')[:14]}"
    distractor = f"train-rag-{stable_digest(f'{index}:d')[:14]}"
    marker_a = f"RAGA{stable_digest(str(index))[:10]}"
    marker_b = f"RAGB{stable_digest(str(index))[:10]}"
    task = task_id("studyhub_rlv3_rag", str(index))
    goal_variants = (
        "请核对{topic}的关键学习步骤，给出结论并引用资料。",
        "我正在复习{topic}。请从资料中确认最重要的操作顺序，并标注来源。",
        "针对{topic}，找出资料明确要求的解题顺序；不要依据热度猜测。",
        "请查证{topic}的核心方法，说明先做什么、后做什么，并附引用。",
    )
    goal = goal_variants[(index // len(_COURSES)) % len(goal_variants)].format(topic=topic)
    docs = [
        {
            "source_id": source_a,
            "material_id": 700000 + index,
            "title": f"{topic}学习清单 {marker_a}",
            "text": f"课程核对记录：{topic}的关键步骤是{principle}。",
            "access_scope": "free",
            "source_quality": "training_verified_note",
        },
        {
            "source_id": source_b,
            "material_id": 800000 + index,
            "title": f"{topic}助教复核 {marker_b}",
            "text": f"助教的独立复核得到同一结论：{principle}。",
            "access_scope": "free",
            "source_quality": "training_verified_note",
        },
        {
            "source_id": distractor,
            "material_id": 900000 + index,
            "title": f"{course}其他章节提示",
            "text": f"本条讨论 {course} 的其他章节，不适用于 {code}。",
            "access_scope": "free",
        },
    ]
    tools = ["knowledge_search", "knowledge_read"]
    tier = "short"
    public = _public_task(
        task=task,
        goal=goal,
        family="rag_and_multihop",
        source_dataset="studyhub_rlv3_rag",
        source_id=str(index),
        source_group_id=f"rlv3-rag-group-{index}",
        tools=tools,
        tier=tier,
        initial_state={},
        citations=True,
        origin="training_only_simulator",
        template_id=f"rag-{index % 96}",
    )
    environment = _replay_environment(task=task, tools=tools, tier=tier, documents=docs)
    claims = [
        {
            "claim_id": "method",
            "required": True,
            "acceptable_semantic_answers": [[principle]],
            "support_source_ids": [source_a, source_b],
            "citation_required": True,
        }
    ]
    verifier = _verifier(
        task=task,
        family="rag_and_multihop",
        objective={"mode": "facts", "acceptable_answers": [[principle]]},
        claims=claims,
        max_tool_calls=4,
        process={"max_reasonable_tool_calls": 2, "target_evidence_gain_steps": 1},
    )
    final_a = f"{topic}的关键步骤是{principle}。[{source_a}]"
    final_b = f"复核结果一致：{principle}。[{source_b}]"
    return _bundle(
        public,
        environment,
        verifier,
        [
            {"name": "knowledge_search", "arguments": {"query": marker_a, "limit": 5}},
            {"name": "knowledge_read", "arguments": {"source_id": source_a}},
        ],
        final_a,
        alternative_actions=[
            {"name": "knowledge_search", "arguments": {"query": marker_b, "limit": 5}},
            {"name": "knowledge_read", "arguments": {"source_id": source_b}},
        ],
        alternative_final_answer=final_b,
    )


def custom_web(index: int) -> dict[str, Any]:
    course, topic, code = _topic(index + 20000)
    current = _OFFICIAL_VALUES[index % len(_OFFICIAL_VALUES)]
    stale = _OFFICIAL_VALUES[(index + 1) % len(_OFFICIAL_VALUES)]
    task = task_id("studyhub_rlv3_web", str(index))
    official_source = f"train-web-{stable_digest(f'{index}:official')[:14]}"
    stale_source = f"train-web-{stable_digest(f'{index}:stale')[:14]}"
    official_url = f"https://training.example.edu/{code.casefold()}/notice"
    stale_url = f"https://archive.example.net/{code.casefold()}/notice"
    official_marker = f"WEBO{stable_digest(str(index))[:10]}"
    stale_marker = f"WEBS{stable_digest(str(index))[:10]}"
    pages = [
        {
            "source_id": official_source,
            "url": official_url,
            "title": f"{topic}官方通知 {official_marker}",
            "snippet": "最新安排",
            "content": f"发布于 2026-08-01。{topic}的有效安排：{current}。",
            "published_at": "2026-08-01",
            "source_quality": "official",
        },
        {
            "source_id": stale_source,
            "url": stale_url,
            "title": f"{topic}旧版转载 {stale_marker}",
            "snippet": "历史安排",
            "content": f"归档于 2025-03-01。旧安排为：{stale}。",
            "published_at": "2025-03-01",
            "source_quality": "secondary_archive",
        },
    ]
    goals = (
        "请查明{topic}目前生效的安排，并优先采用官方来源，附上引用。",
        "网上有新旧两版{topic}通知，请确认当前有效内容并说明依据。",
        "核对{topic}的最新公开通知；遇到旧转载时不要把它当成现行要求。",
        "请从公开网页确认{topic}现在执行的规定，并标注来源。",
    )
    tools = ["web_search", "web_fetch"]
    tier = "short"
    public = _public_task(
        task=task,
        goal=goals[index % len(goals)].format(topic=topic),
        family="web",
        source_dataset="studyhub_rlv3_web",
        source_id=str(index),
        source_group_id=f"rlv3-web-group-{index}",
        tools=tools,
        tier=tier,
        initial_state={},
        citations=True,
        origin="training_only_web_snapshot",
        template_id=f"web-{index % 128}",
    )
    environment = _replay_environment(task=task, tools=tools, tier=tier, web_pages=pages)
    verifier = _verifier(
        task=task,
        family="web",
        objective={"mode": "facts", "acceptable_answers": [[current]]},
        claims=[
            {
                "claim_id": "current_notice",
                "required": True,
                "acceptable_semantic_answers": [[current]],
                "support_source_ids": [official_source],
                "citation_required": True,
                "contradiction_patterns": [stale],
            }
        ],
        max_tool_calls=4,
        process={"max_reasonable_tool_calls": 2, "target_evidence_gain_steps": 1},
    )
    final = f"当前生效安排是：{current}。[{official_source}]"
    return _bundle(
        public,
        environment,
        verifier,
        [
            {"name": "web_search", "arguments": {"query": official_marker, "limit": 5}},
            {"name": "web_fetch", "arguments": {"url": official_url}},
        ],
        final,
    )


def custom_memory(index: int) -> dict[str, Any]:
    course, topic, code = _topic(index + 40000)
    current = _PREFERENCES[index % len(_PREFERENCES)]
    stale = _PREFERENCES[(index + 1) % len(_PREFERENCES)]
    task = task_id("studyhub_rlv3_memory", str(index))
    user_id = f"memory-user-{index}"
    memories = [
        {
            "source_id": f"mem-current-{stable_digest(str(index))[:12]}",
            "user_id": user_id,
            "content": f"{code} 当前偏好：{current}",
            "recorded_at": "2026-08-01",
            "valid_until": "2027-01-01",
            "status": "current",
        },
        {
            "source_id": f"mem-stale-{stable_digest(str(index))[:12]}",
            "user_id": user_id,
            "content": f"{code} 旧偏好：{stale}",
            "recorded_at": "2025-01-01",
            "valid_until": "2025-06-01",
            "status": "stale",
        },
        {
            "source_id": f"mem-other-{stable_digest(str(index))[:12]}",
            "user_id": f"other-{index}",
            "content": f"{code} 其他用户偏好：不要向当前用户暴露。",
            "recorded_at": "2026-08-01",
            "status": "current",
        },
    ]
    tools = ["personal_memory_search"]
    tier = "short"
    goals = (
        "结合我对{topic}的当前学习偏好，给出一条具体复习建议；过期偏好不要覆盖新记录。",
        "请查看我与{topic}相关的最新偏好，再安排下一次学习步骤。",
        "我想继续学习{topic}，请使用当前个人记忆而不是其他用户或旧记录。",
        "基于我最近记录的{topic}学习方式，简要说明今天先做什么。",
    )
    public = _public_task(
        task=task,
        goal=goals[index % len(goals)].format(topic=topic),
        family="memory",
        source_dataset="studyhub_rlv3_memory",
        source_id=str(index),
        source_group_id=f"rlv3-memory-group-{index}",
        tools=tools,
        tier=tier,
        initial_state={"memory_scope": "current_user_only"},
        citations=False,
        origin="training_only_memory",
        template_id=f"memory-{index % 128}",
    )
    environment = _replay_environment(
        task=task,
        tools=tools,
        tier=tier,
        identity={"user_id": user_id},
        personal_memories=memories,
    )
    verifier = _verifier(
        task=task,
        family="memory",
        objective={"mode": "facts", "acceptable_answers": [[current]]},
        max_tool_calls=4,
        process={"max_reasonable_tool_calls": 1, "target_evidence_gain_steps": 1},
        extra_constraints={"forbidden_answer_strings": ["不要向当前用户暴露"]},
    )
    return _bundle(
        public,
        environment,
        verifier,
        [{"name": "personal_memory_search", "arguments": {"query": f"{topic} {code}", "limit": 5}}],
        f"根据当前偏好，建议{current}。",
    )


def custom_state_function(index: int) -> dict[str, Any]:
    course, topic, _ = _topic(index + 60000)
    task = task_id("studyhub_rlv3_state", str(index))
    material_id = 1100000 + index
    status = ("learning", "review", "mastered")[index % 3]
    source = f"train-state-{stable_digest(str(index))[:14]}"
    docs = [
        {
            "source_id": source,
            "material_id": material_id,
            "title": f"{topic}公开资料",
            "text": f"{topic}的公开学习资料。",
            "access_scope": "free",
        }
    ]
    tools = ["material_bookmark_add", "learning_progress_record"]
    tier = "short"
    public = _public_task(
        task=task,
        goal=f"把资料 {material_id} 加入书签，并把{topic}的学习状态记录为 {status}。完成后简要确认。",
        family="function_calling",
        source_dataset="studyhub_rlv3_state",
        source_id=str(index),
        source_group_id=f"rlv3-state-group-{index}",
        tools=tools,
        tier=tier,
        initial_state={"bookmarks": [], "progress": {}},
        citations=False,
        origin="training_only_state",
        template_id=f"state-{index % 96}",
    )
    environment = _replay_environment(
        task=task,
        tools=tools,
        tier=tier,
        documents=docs,
        initial_state={"bookmarks": [], "progress": {}},
    )
    verifier = _verifier(
        task=task,
        family="function_calling",
        objective={
            "mode": "state",
            "state_assertions": [
                {"path": "bookmarks", "operator": "contains", "value": material_id},
                {"path": f"progress.{topic}.status", "operator": "eq", "value": status},
            ],
        },
        max_tool_calls=4,
        process={"max_reasonable_tool_calls": 2},
    )
    first = {"name": "material_bookmark_add", "arguments": {"material_id": material_id}}
    second = {
        "name": "learning_progress_record",
        "arguments": {"topic": topic, "status": status},
    }
    return _bundle(
        public,
        environment,
        verifier,
        [first, second],
        "书签和学习状态均已更新。",
        alternative_actions=[second, first],
        alternative_final_answer="学习状态与书签已经完成更新。",
    )


def custom_cross_tool(index: int) -> dict[str, Any]:
    course, topic, code = _topic(index + 80000)
    task = task_id("studyhub_rlv3_cross", str(index))
    user_id = f"cross-user-{index}"
    preference = _PREFERENCES[index % len(_PREFERENCES)]
    principle = _PRINCIPLES[(index + 3) % len(_PRINCIPLES)]
    material_id = 1200000 + index
    source = f"train-cross-{stable_digest(str(index))[:14]}"
    docs = [
        {
            "source_id": source,
            "material_id": material_id,
            "title": f"{topic}复习资料",
            "text": f"{code} 对应资料建议：{principle}。",
            "access_scope": "free",
        }
    ]
    memories = [
        {
            "source_id": f"cross-memory-{stable_digest(str(index))[:12]}",
            "user_id": user_id,
            "content": f"{code} 当前学习偏好：{preference}",
            "recorded_at": "2026-08-02",
            "status": "current",
        }
    ]
    tools = ["personal_memory_search", "knowledge_search", "knowledge_read", "study_plan_update"]
    tier = "extended"
    public = _public_task(
        task=task,
        goal=(
            f"结合我对{topic}的当前学习偏好和可用资料，制定每周 180 分钟的计划；"
            "计划中只使用已核对的公开资料，并在回答中引用资料依据。"
        ),
        family="cross_tool",
        source_dataset="studyhub_rlv3_cross",
        source_id=str(index),
        source_group_id=f"rlv3-cross-group-{index}",
        tools=tools,
        tier=tier,
        initial_state={"study_plans": {}},
        citations=True,
        origin="training_only_composed",
        template_id=f"cross-{index % 160}",
    )
    environment = _replay_environment(
        task=task,
        tools=tools,
        tier=tier,
        identity={"user_id": user_id},
        initial_state={"study_plans": {}},
        documents=docs,
        personal_memories=memories,
    )
    verifier = _verifier(
        task=task,
        family="cross_tool",
        objective={
            "mode": "facts_and_state",
            "acceptable_answers": [[preference], [principle]],
            "state_assertions": [
                {"path": f"study_plans.{topic}.weekly_minutes", "operator": "eq", "value": 180},
                {"path": f"study_plans.{topic}.resource_ids", "operator": "contains", "value": material_id},
            ],
        },
        claims=[
            {
                "claim_id": "resource_method",
                "required": True,
                "acceptable_semantic_answers": [[principle]],
                "support_source_ids": [source],
                "citation_required": True,
            }
        ],
        max_tool_calls=10,
        process={"max_reasonable_tool_calls": 4, "target_evidence_gain_steps": 2},
    )
    actions = [
        {"name": "personal_memory_search", "arguments": {"query": f"{topic} {code}", "limit": 5}},
        {"name": "knowledge_search", "arguments": {"query": f"{topic} {code}", "limit": 5}},
        {"name": "knowledge_read", "arguments": {"source_id": source}},
        {
            "name": "study_plan_update",
            "arguments": {"topic": topic, "weekly_minutes": 180, "resource_ids": [material_id]},
        },
    ]
    final = f"计划已按“{preference}”设置；资料建议是{principle}。[{source}]"
    return _bundle(public, environment, verifier, actions, final)


def custom_recovery(index: int) -> dict[str, Any]:
    course, topic, code = _topic(index + 100000)
    task = task_id("studyhub_rlv3_recovery", str(index))
    principle = _PRINCIPLES[(index + 5) % len(_PRINCIPLES)]
    public_source = f"train-recovery-{stable_digest(f'{index}:public')[:14]}"
    private_source = f"train-recovery-{stable_digest(f'{index}:private')[:14]}"
    public_marker = f"RECOVERY{stable_digest(str(index))[:10]}"
    tools = ["knowledge_search", "knowledge_read"]
    tier = "extended"
    mode = index % 3
    docs = [
        {
            "source_id": public_source,
            "material_id": 1300000 + index,
            "title": f"{topic}公开替代资料 {public_marker}",
            "text": f"公开结论：{principle}。",
            "access_scope": "free",
        },
        {
            "source_id": private_source,
            "material_id": 1400000 + index,
            "title": f"{topic}受限资料",
            "text": "PRIVATE_SENTINEL_DO_NOT_DISCLOSE",
            "access_scope": "private",
            "owner_id": f"other-{index}",
        },
    ]
    failure_schedule: list[dict[str, Any]] = []
    direct_allowlist: list[str] = []
    allow_denial = False
    forbidden_sources: list[str] = []
    if mode == 0:
        goal = f"请查找{topic}的公开结论并引用依据；遇到一次临时检索失败时应安全重试。"
        failure_schedule = [
            {"tool": "knowledge_search", "occurrence": 1, "error_code": "provider_timeout", "retryable": True}
        ]
        actions = [
            {"name": "knowledge_search", "arguments": {"query": f"首次尝试 {code}", "limit": 5}},
            {"name": "knowledge_search", "arguments": {"query": public_marker, "limit": 5}},
            {"name": "knowledge_read", "arguments": {"source_id": public_source}},
        ]
    elif mode == 1:
        goal = (
            f"我收到一个资料引用 {private_source}，请尝试读取；若无权限，改用{topic}的公开替代资料，不得推测受限内容。"
        )
        direct_allowlist = [private_source]
        allow_denial = True
        actions = [
            {"name": "knowledge_read", "arguments": {"source_id": private_source}},
            {"name": "knowledge_search", "arguments": {"query": public_marker, "limit": 5}},
            {"name": "knowledge_read", "arguments": {"source_id": public_source}},
        ]
    else:
        goal = f"只使用{topic}的公开资料回答并引用；不要尝试访问任何标为受限的资料。"
        forbidden_sources = [private_source]
        actions = [
            {"name": "knowledge_search", "arguments": {"query": public_marker, "limit": 5}},
            {"name": "knowledge_read", "arguments": {"source_id": public_source}},
        ]
    public = _public_task(
        task=task,
        goal=goal,
        family="recovery_and_acl",
        source_dataset="studyhub_rlv3_recovery",
        source_id=str(index),
        source_group_id=f"rlv3-recovery-group-{index}",
        tools=tools,
        tier=tier,
        initial_state={},
        citations=True,
        origin="training_only_recovery",
        template_id=f"recovery-{index % 144}",
    )
    environment = _replay_environment(
        task=task,
        tools=tools,
        tier=tier,
        documents=docs,
        failure_schedule=failure_schedule,
        direct_read_allowlist=direct_allowlist,
    )
    constraints: dict[str, Any] = {
        "forbidden_answer_strings": ["PRIVATE_SENTINEL_DO_NOT_DISCLOSE"],
        "forbidden_source_ids": forbidden_sources,
    }
    if allow_denial:
        constraints["allow_permission_denied"] = True
    verifier = _verifier(
        task=task,
        family="recovery_and_acl",
        objective={"mode": "facts", "acceptable_answers": [[principle]]},
        claims=[
            {
                "claim_id": "public_alternative",
                "required": True,
                "acceptable_semantic_answers": [[principle]],
                "support_source_ids": [public_source],
                "citation_required": True,
            }
        ],
        max_tool_calls=10,
        process={
            "max_reasonable_tool_calls": len(actions),
            "target_evidence_gain_steps": 1,
            "recovery_expected": mode in {0, 1},
        },
        extra_constraints=constraints,
    )
    final = f"公开资料给出的结论是{principle}。[{public_source}]"
    return _bundle(public, environment, verifier, actions, final)


def custom_long_horizon(index: int) -> dict[str, Any]:
    course, topic, code = _topic(index + 120000)
    task = task_id("studyhub_rlv3_long", str(index))
    preference = _PREFERENCES[index % len(_PREFERENCES)]
    facts = [
        f"目标章节是第{index % 9 + 1}章",
        f"先修条件是{_PRINCIPLES[index % len(_PRINCIPLES)]}",
        f"练习数量为{index % 5 + 3}组",
        f"复盘节点安排在第{index % 4 + 2}天",
    ]
    sources = [f"train-long-{stable_digest(f'{index}:{part}')[:14]}" for part in range(4)]
    markers = [f"LONG{part}{stable_digest(f'{index}:{part}')[:10]}" for part in range(4)]
    documents = []
    for position, (source, fact, marker) in enumerate(zip(sources, facts, markers, strict=True)):
        row = {
            "source_id": source,
            "material_id": 1500000 + index * 10 + position,
            "title": f"{topic}研究步骤{position + 1} {marker}",
            "text": f"本步骤证据：{fact}。",
            "access_scope": "free",
            "source_quality": "training_verified_note",
        }
        if position:
            row["unlock_after_source_ids"] = [sources[position - 1]]
        documents.append(row)
    web_value = _OFFICIAL_VALUES[index % len(_OFFICIAL_VALUES)]
    web_source = f"train-long-web-{stable_digest(str(index))[:12]}"
    web_url = f"https://training.example.edu/research/{code.casefold()}"
    web_marker = f"LONGWEB{stable_digest(str(index))[:10]}"
    pages = [
        {
            "source_id": web_source,
            "url": web_url,
            "title": f"{topic}官方补充 {web_marker}",
            "content": f"当前补充要求：{web_value}。",
            "snippet": "当前补充要求",
            "published_at": "2026-08-01",
            "source_quality": "official",
        }
    ]
    user_id = f"long-user-{index}"
    memories = [
        {
            "source_id": f"long-memory-{stable_digest(str(index))[:12]}",
            "user_id": user_id,
            "content": f"{code} 当前学习偏好：{preference}",
            "recorded_at": "2026-08-02",
            "status": "current",
        }
    ]
    tools = ["knowledge_search", "knowledge_read", "web_search", "web_fetch", "personal_memory_search"]
    tier = "research"
    public = _public_task(
        task=task,
        goal=(
            f"为{topic}制定一份有证据的学习安排。必须依次核对四个相互依赖的资料步骤，"
            "再检查最新公开补充和我的当前偏好；说明发现、证据、限制和建议。"
        ),
        family="long_horizon_and_deep_research",
        source_dataset="studyhub_rlv3_long",
        source_id=str(index),
        source_group_id=f"rlv3-long-group-{index}",
        tools=tools,
        tier=tier,
        initial_state={"memory_scope": "current_user_only"},
        citations=True,
        origin="training_only_long_horizon",
        template_id=f"long-{index % 192}",
    )
    environment = _replay_environment(
        task=task,
        tools=tools,
        tier=tier,
        identity={"user_id": user_id},
        documents=documents,
        web_pages=pages,
        personal_memories=memories,
    )
    claims = [
        {
            "claim_id": f"step_{position + 1}",
            "required": True,
            "acceptable_semantic_answers": [[fact]],
            "support_source_ids": [source],
            "citation_required": True,
        }
        for position, (source, fact) in enumerate(zip(sources, facts, strict=True))
    ]
    claims.append(
        {
            "claim_id": "current_web",
            "required": True,
            "acceptable_semantic_answers": [[web_value]],
            "support_source_ids": [web_source],
            "citation_required": True,
        }
    )
    requirements = [
        {"id": "limitations", "weight": 1.0, "acceptable_terms": [["限制", "局限", "不足"]]},
        {"id": "recommendation", "weight": 1.0, "acceptable_terms": [["建议", "安排", "计划"]]},
    ]
    verifier = _verifier(
        task=task,
        family="long_horizon_and_deep_research",
        objective={
            "mode": "facts",
            "acceptable_answers": [[fact] for fact in facts] + [[web_value], [preference]],
        },
        claims=claims,
        semantic_requirements=requirements,
        max_tool_calls=18,
        process={"max_reasonable_tool_calls": 11, "target_evidence_gain_steps": 6},
    )
    actions: list[dict[str, Any]] = []
    for source, marker in zip(sources, markers, strict=True):
        actions.extend(
            [
                {
                    "name": "knowledge_search",
                    "arguments": {"query": marker, "limit": 5},
                },
                {"name": "knowledge_read", "arguments": {"source_id": source}},
            ]
        )
    actions.extend(
        [
            {"name": "web_search", "arguments": {"query": web_marker, "limit": 5}},
            {"name": "web_fetch", "arguments": {"url": web_url}},
            {"name": "personal_memory_search", "arguments": {"query": f"{topic} {code}", "limit": 5}},
        ]
    )
    cited = "；".join(f"{fact}。[{source}]" for fact, source in zip(facts, sources, strict=True))
    final = (
        f"发现：{cited} 当前补充为{web_value}。[{web_source}] 偏好为{preference}。"
        "限制：这是冻结训练快照；建议据此分步执行。"
    )
    return _bundle(public, environment, verifier, actions, final)


def custom_direct(index: int) -> dict[str, Any]:
    course, topic, _ = _topic(index + 140000)
    task = task_id("studyhub_rlv3_direct", str(index))
    tier = "direct"
    if index % 2 == 0:
        sessions = index % 5 + 3
        minutes = (index % 4 + 2) * 15
        answer = str(sessions * minutes)
        goal = f"我为{topic}安排了 {sessions} 次学习，每次 {minutes} 分钟。总共多少分钟？"
        objective = {"mode": "facts", "acceptable_answers": [[answer]]}
        final = f"总时长是 {answer} 分钟。"
        template = "direct-arithmetic"
    else:
        goal = f"{topic}下一次临时口试的确切日期是什么？请给出确定日期。"
        objective = {"mode": "abstain", "forbidden_specifics": ["2026-09-18", "2026-10-01"]}
        final = "当前没有可核验的通知或工具结果，证据不足，无法确认确切日期。"
        template = "direct-evidence-abstention"
    public = _public_task(
        task=task,
        goal=goal,
        family="direct_answer_and_abstention",
        source_dataset="studyhub_rlv3_direct",
        source_id=str(index),
        source_group_id=f"rlv3-direct-group-{index}",
        tools=[],
        tier=tier,
        initial_state={},
        citations=False,
        origin="training_only_direct",
        template_id=f"{template}-{index % 64}",
    )
    environment = {
        "schema_version": ENVIRONMENT_V3_SCHEMA,
        "environment_kind": "fixture",
        "task_id": task,
        "initial_state": {},
        "max_tool_calls": 1,
        "mutating_tools": [],
        "tool_schemas": [],
        "fixture_routes": [],
    }
    verifier = _verifier(
        task=task,
        family="direct_answer_and_abstention",
        objective=objective,
        max_tool_calls=1,
        process={"max_reasonable_tool_calls": 0},
        extra_constraints={"forbidden_tools": ["knowledge_search", "web_search"]},
    )
    return _bundle(public, environment, verifier, [], final)


CUSTOM_FACTORIES = {
    "function_calling": custom_state_function,
    "rag_and_multihop": custom_rag,
    "web": custom_web,
    "memory": custom_memory,
    "cross_tool": custom_cross_tool,
    "recovery_and_acl": custom_recovery,
    "long_horizon_and_deep_research": custom_long_horizon,
    "direct_answer_and_abstention": custom_direct,
}


def convert_function_candidate(row: dict[str, Any], family: str) -> dict[str, Any]:
    source_dataset = str(row["source_dataset"])
    source_id = str(row["source_id"])
    task = task_id(f"external_{source_dataset}_{family}", source_id)
    routes = list((row.get("fixture") or {}).get("routes", []))
    expected_calls = list(row["verifier"].get("expected_calls", []))
    if not routes or not expected_calls:
        raise ValueError("function candidate lacks executable routes")
    schemas_by_name: dict[str, dict[str, Any]] = {}
    for tool in row["tools"]:
        name = str(tool["name"])
        schemas_by_name.setdefault(
            name,
            {
                "name": name,
                "description": tool.get("description", name),
                "parameters": _normalize_external_schema(tool.get("parameters", {"type": "object", "properties": {}})),
            },
        )
    schemas = list(schemas_by_name.values())
    fixture_routes = []
    for index, route in enumerate(routes):
        raw_result = copy.deepcopy(route.get("result"))
        if isinstance(raw_result, dict):
            result = raw_result
            result.setdefault("ok", True)
        else:
            result = {"ok": True, "content": raw_result}
        fixture_routes.append(
            {
                "name": route["name"],
                "arguments": copy.deepcopy(route.get("arguments", {})),
                "result": result,
                "state_patch": {"completed": {str(index): True}},
            }
        )
    tier = "extended" if len(expected_calls) >= 3 else "short"
    public = _public_task(
        task=task,
        goal=row["user_request"],
        family=family,
        source_dataset=source_dataset,
        source_id=source_id,
        source_group_id=f"external:{source_dataset}:{row['group_id']}",
        tools=[schema["name"] for schema in schemas],
        tier=tier,
        initial_state={"completed": {}},
        citations=False,
        origin="open_source_executable_fixture",
        template_id=f"{source_dataset}-{stable_digest(source_id, salt='template')[:12]}",
    )
    environment = {
        "schema_version": ENVIRONMENT_V3_SCHEMA,
        "environment_kind": "fixture",
        "task_id": task,
        "initial_state": {"completed": {}},
        "max_tool_calls": budget_for(tier)["max_tool_calls"],
        "mutating_tools": [],
        "tool_schemas": schemas,
        "fixture_routes": fixture_routes,
    }
    assertions = [
        {"path": f"completed.{index}", "operator": "eq", "value": True} for index in range(len(expected_calls))
    ]
    verifier = _verifier(
        task=task,
        family=family,
        objective={"mode": "state", "state_assertions": assertions},
        max_tool_calls=budget_for(tier)["max_tool_calls"],
        process={"max_reasonable_tool_calls": len(expected_calls)},
    )
    final = clean(next(iter(row["verifier"].get("expected_answers", [])), ""))
    if not final:
        final = "The requested operation completed successfully."
    actions = [{"name": call["name"], "arguments": copy.deepcopy(call.get("arguments", {}))} for call in expected_calls]
    alternative = list(reversed(actions)) if len(actions) > 1 else []
    return _bundle(
        public,
        environment,
        verifier,
        actions,
        final,
        alternative_actions=alternative,
        alternative_final_answer=final if alternative else "",
    )


def convert_search_candidate(row: dict[str, Any], family: str) -> dict[str, Any]:
    source_dataset = str(row["source_dataset"])
    source_id = str(row["source_id"])
    task = task_id(f"external_{source_dataset}_{family}", source_id)
    documents = [
        {
            **copy.deepcopy(document),
            "access_scope": "free",
            "source_quality": "open_dataset_context",
        }
        for document in row["documents"]
    ]
    gold_sources = list(map(str, row["verifier"].get("gold_source_ids", [])))
    expected = clean(next(iter(row["verifier"].get("expected_answers", [])), ""))
    if not expected:
        raise ValueError("search candidate lacks a verifier answer")
    tier = "research" if family == "long_horizon_and_deep_research" else "extended"
    public = _public_task(
        task=task,
        goal=row["user_request"],
        family=family,
        source_dataset=source_dataset,
        source_id=source_id,
        source_group_id=f"external:{source_dataset}:{row['group_id']}",
        tools=["knowledge_search", "knowledge_read"],
        tier=tier,
        initial_state={},
        citations=bool(gold_sources),
        origin="open_source_frozen_corpus",
        template_id=f"{source_dataset}-{stable_digest(source_id, salt='template')[:12]}",
    )
    environment = _replay_environment(
        task=task,
        tools=["knowledge_search", "knowledge_read"],
        tier=tier,
        documents=documents,
    )
    if gold_sources:
        objective = {"mode": "facts", "acceptable_answers": [[expected]]}
        claims = [
            {
                "claim_id": "answer",
                "required": True,
                "acceptable_semantic_answers": [[expected]],
                "support_source_ids": gold_sources,
                "citation_required": True,
            }
        ]
    else:
        objective = {"mode": "abstain", "forbidden_specifics": []}
        claims = []
    verifier = _verifier(
        task=task,
        family=family,
        objective=objective,
        claims=claims,
        max_tool_calls=budget_for(tier)["max_tool_calls"],
        process={
            "max_reasonable_tool_calls": min(budget_for(tier)["max_tool_calls"], max(2, len(gold_sources) * 2)),
            "target_evidence_gain_steps": len(gold_sources) if gold_sources else 1,
        },
    )
    by_id = {str(document["source_id"]): document for document in documents}
    actions: list[dict[str, Any]] = []
    for source in gold_sources:
        document = by_id[source]
        query = clean(document.get("title")) or expected
        actions.extend(
            [
                {"name": "knowledge_search", "arguments": {"query": query, "limit": 10}},
                {"name": "knowledge_read", "arguments": {"source_id": source}},
            ]
        )
    final = expected
    if gold_sources:
        final += " " + " ".join(f"[{source}]" for source in gold_sources)
    return _bundle(public, environment, verifier, actions, final)


def convert_coig_candidate(index: int, row: dict[str, Any]) -> dict[str, Any]:
    source_id = str(index)
    task = task_id("external_coig_exam", source_id)
    instruction = clean(row.get("textbox_q_instruction"))
    context = clean(row.get("textbox_q_context"))
    question = clean(row.get("textbox_question"))
    answer = clean(row.get("textbox_answer"))
    analysis = clean(row.get("textbox_answer_analysis"))
    goal = "\n\n".join(part for part in (instruction, context, question) if part)
    public = _public_task(
        task=task,
        goal=goal,
        family="direct_answer_and_abstention",
        source_dataset="coig_exam",
        source_id=source_id,
        source_group_id=f"external:coig_exam:{source_id}",
        tools=[],
        tier="direct",
        initial_state={},
        citations=False,
        origin="open_source_direct_qa",
        template_id=f"coig-{stable_digest(goal, salt='template')[:12]}",
    )
    environment = {
        "schema_version": ENVIRONMENT_V3_SCHEMA,
        "environment_kind": "fixture",
        "task_id": task,
        "initial_state": {},
        "max_tool_calls": 1,
        "mutating_tools": [],
        "tool_schemas": [],
        "fixture_routes": [],
    }
    verifier = _verifier(
        task=task,
        family="direct_answer_and_abstention",
        objective={"mode": "facts", "acceptable_answers": [[answer]]},
        max_tool_calls=1,
        process={"max_reasonable_tool_calls": 0},
    )
    final = f"答案：{answer}。"
    if analysis:
        final += analysis
    return _bundle(public, environment, verifier, [], final)
