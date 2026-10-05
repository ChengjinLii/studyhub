from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

_VERSION = re.compile(r"^\d+\.\d+$")

SYSTEM_PROMPT_KEY = "studyhub.agent.system@1.0"
FINALIZE_PROMPT_KEY = "studyhub.agent.finalize@1.0"
VERIFY_FEEDBACK_PROMPT_KEY = "studyhub.agent.verify_feedback@1.0"
PLAN_REQUEST_PROMPT_KEY = "studyhub.agent.plan_request@1.0"
PLAN_REMINDER_PROMPT_KEY = "studyhub.agent.plan_reminder@1.0"
COMPACTION_NOTE_PROMPT_KEY = "studyhub.agent.compaction_note@1.0"

_SYSTEM_TEXT = """你是 StudyHub 学习助手，服务高校学生查找学习资料、了解平台规则。
工作方式：
- 需要事实时先调用工具检索，不要凭记忆编造资料名称、页码或政策条款。
- 读取资料内容前必须先通过 materials_search 或 materials_recommend 找到它。
- 回答时引用你实际读到的资料，格式为 [资料ID:页码]；没有读到的内容不要引用。
- 工具返回错误时根据错误调整参数，不要重复同样的调用。
- 信息足够后直接给出简洁的中文回答；不要在同一条回复里既调用工具又给出最终回答。"""

_FINALIZE_TEXT = "这是最后一轮。请不要再调用工具，根据已经获得的信息直接给出最终回答；信息不足时说明缺少什么。"

_VERIFY_FEEDBACK_TEXT = (
    "你的回答引用未通过核查：只能引用本次对话中实际读过的资料页（格式 [资料ID:页码]）；"
    "如果读过资料却没有引用，请补上引用；如果信息不足，请说明。请修改后重新给出最终回答。"
)

_PLAN_REQUEST_TEXT = (
    "请先给出三至六步的简短编号计划，说明需要检索、读取或核对什么；"
    "本轮只写计划，不调用工具，也不要把未经查证的信息写成答案。后续再按计划执行。"
)

_PLAN_REMINDER_TEXT = (
    "请按计划执行，需要事实时调用工具，信息足够后给出最终回答。"
    "可根据工具反馈调整计划；计划不是资料证据，引用仍须来自实际读过的页面。"
)

_COMPACTION_NOTE_TEXT = (
    "较早的工具结果已压缩，标记 compacted 的 result 仅保留摘要，正文可能截断。"
    "资料标识、页码和数值沿用原结果；需要完整内容时重新读取，不要补写缺失信息。"
)


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    prompt_id: str
    version: str
    text: str

    def __post_init__(self) -> None:
        if not self.prompt_id.strip():
            raise ValueError("prompt_id must not be empty")
        if not _VERSION.match(self.version):
            raise ValueError(f"prompt {self.prompt_id}: version {self.version!r} must look like 1.0")

    @property
    def key(self) -> str:
        return f"{self.prompt_id}@{self.version}"


class PromptRegistry:
    def __init__(self, prompts: Iterable[PromptTemplate] = ()) -> None:
        mapping: dict[str, PromptTemplate] = {}
        for prompt in prompts:
            if prompt.key in mapping:
                raise ValueError(f"duplicate prompt {prompt.key}")
            mapping[prompt.key] = prompt
        self._prompts = MappingProxyType(mapping)

    def get(self, key: str) -> PromptTemplate:
        try:
            return self._prompts[key]
        except KeyError:
            raise KeyError(f"unknown prompt {key!r}; known: {', '.join(sorted(self._prompts))}") from None

    def with_prompt(self, prompt: PromptTemplate) -> PromptRegistry:
        return PromptRegistry([*self._prompts.values(), prompt])

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._prompts))


DEFAULT_PROMPTS = PromptRegistry(
    [
        PromptTemplate("studyhub.agent.system", "1.0", _SYSTEM_TEXT),
        PromptTemplate("studyhub.agent.finalize", "1.0", _FINALIZE_TEXT),
        PromptTemplate("studyhub.agent.verify_feedback", "1.0", _VERIFY_FEEDBACK_TEXT),
        PromptTemplate("studyhub.agent.plan_request", "1.0", _PLAN_REQUEST_TEXT),
        PromptTemplate("studyhub.agent.plan_reminder", "1.0", _PLAN_REMINDER_TEXT),
        PromptTemplate("studyhub.agent.compaction_note", "1.0", _COMPACTION_NOTE_TEXT),
    ]
)
