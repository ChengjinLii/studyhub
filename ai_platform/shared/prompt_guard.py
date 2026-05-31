from __future__ import annotations

import re
from dataclasses import dataclass


INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_instructions", re.compile(r"忽略(以上|之前|所有).{0,12}(规则|指令|要求)|ignore (all |previous |above )?instructions", re.I)),
    ("reveal_prompt", re.compile(r"系统提示词|system prompt|developer message|prompt全文|显示.*prompt", re.I)),
    ("secret_exfiltration", re.compile(r"api[_ -]?key|密钥|token|环境变量|泄露|导出|打印.*(key|token)", re.I)),
    ("tool_bypass", re.compile(r"绕过(权限|审核|限制)|bypass (auth|policy|safety)|越权|提权", re.I)),
    ("role_override", re.compile(r"你现在是|act as|进入开发者模式|developer mode|jailbreak", re.I)),
)


@dataclass(frozen=True)
class PromptGuardResult:
    risky: bool
    reasons: tuple[str, ...]

    def warnings(self) -> tuple[str, ...]:
        return tuple(f"prompt_injection_risk:{reason}" for reason in self.reasons)


class PromptInjectionGuard:
    def inspect(self, text: str) -> PromptGuardResult:
        reasons = tuple(name for name, pattern in INJECTION_PATTERNS if pattern.search(text or ""))
        return PromptGuardResult(risky=bool(reasons), reasons=reasons)
