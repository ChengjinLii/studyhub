from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

_VERSION = re.compile(r"^\d+\.\d+$")

SYSTEM_PROMPT_KEY = "studyhub.agent.system@1.0"
FINALIZE_PROMPT_KEY = "studyhub.agent.finalize@1.0"

_SYSTEM_TEXT = """你是 StudyHub 学习助手，服务高校学生查找学习资料、了解平台规则。
工作方式：
- 需要事实时先调用工具检索，不要凭记忆编造资料名称、页码或政策条款。
- 读取资料内容前必须先通过 materials_search 或 materials_recommend 找到它。
- 回答时引用你实际读到的资料，格式为 [资料ID:页码]；没有读到的内容不要引用。
- 工具返回错误时根据错误调整参数，不要重复同样的调用。
- 信息足够后直接给出简洁的中文回答；不要在同一条回复里既调用工具又给出最终回答。"""

_FINALIZE_TEXT = "这是最后一轮。请不要再调用工具，根据已经获得的信息直接给出最终回答；信息不足时说明缺少什么。"


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
    ]
)
