from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = ROOT / "studyhub-agent/reports"
REPORTS = (
    "STUDYHUB_AGENT_MODEL_SFT_RL_BRIEF.html",
    "STUDYHUB_AGENT_PROGRESS_2026-08-09.html",
    "STUDYHUB_ROUTER_RL_MATURITY_V2_REPORT.html",
    "STUDYHUB_ROUTER_RL_PILOT_REPORT.html",
    "STUDYHUB_SFT_COMPLETION_REPORT.html",
    "StudyHub_SFT_Experiment_Roadmap.html",
)
FORBIDDEN_VISIBLE_PHRASES = (
    "进步集中",
    "盲区仍在",
    "稳定完成，不代表稳定获益",
    "好信号，不等于放行",
    "证据闭环",
    "最小闭环",
    "SFT 主线",
    "真正修复",
    "唯一胜出",
    "胜出配置",
    "研究候选，不碰生产",
    "一次选择，一次测试",
    "26 项，逐项留证",
    "Maturity v2",
    "Decision first",
    "Executive verdict",
    "做到哪一步了",
    "一眼看懂当前状态",
    "不是 Agent 不能跑",
    "接下来只走这一条路线",
    "不是简单 Chatbot",
    "训练跑完”不等于",
    "真正写成了离线可运行代码",
    "也不应该现在开始",
    "Agent 工程底座",
    "第一阶段底座",
    "已经做了什么",
    "模型实验走到了哪里",
    "还有哪些没有做",
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"style", "script"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"}:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and data.strip():
            self.parts.append(data.strip())


def test_sft_and_rl_reports_avoid_slogan_style_language() -> None:
    for filename in REPORTS:
        parser = _VisibleTextParser()
        parser.feed((REPORT_DIR / filename).read_text(encoding="utf-8"))
        visible_text = " ".join(parser.parts)

        for phrase in FORBIDDEN_VISIBLE_PHRASES:
            assert phrase not in visible_text, f"{filename} contains {phrase!r}"
