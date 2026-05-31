from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ReviewAction(StrEnum):
    APPROVE = "APPROVE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECT = "REJECT"
    HIDE = "HIDE"


@dataclass(frozen=True)
class MaterialSample:
    id: str
    title: str
    description: str
    filename: str
    price_cents: int
    uploader_age_days: int
    uploader_uploads_24h: int
    reports_7d: int
    duplicate_count: int
    metadata: dict[str, Any]

    @property
    def combined_text(self) -> str:
        metadata_text = " ".join(str(value) for value in self.metadata.values() if value)
        return f"{self.title}\n{self.description}\n{self.filename}\n{metadata_text}"


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    category: str
    weight: int
    severity: str
    reason: str


@dataclass(frozen=True)
class ModerationRule:
    id: str
    category: str
    weight: int
    severity: str
    reason: str
    text_patterns: tuple[str, ...] = ()
    filename_patterns: tuple[str, ...] = ()
    min_reports_7d: int | None = None
    min_duplicate_count: int | None = None
    max_uploader_age_days: int | None = None
    min_uploads_24h: int | None = None
    min_price_cents: int | None = None
    require_empty_description: bool = False

    def match(self, material: MaterialSample) -> RuleMatch | None:
        if self.text_patterns and not _matches_any(material.combined_text, self.text_patterns):
            return None
        if self.filename_patterns and not _matches_any(material.filename, self.filename_patterns):
            return None
        if self.min_reports_7d is not None and material.reports_7d < self.min_reports_7d:
            return None
        if self.min_duplicate_count is not None and material.duplicate_count < self.min_duplicate_count:
            return None
        if self.max_uploader_age_days is not None and material.uploader_age_days > self.max_uploader_age_days:
            return None
        if self.min_uploads_24h is not None and material.uploader_uploads_24h < self.min_uploads_24h:
            return None
        if self.min_price_cents is not None and material.price_cents < self.min_price_cents:
            return None
        if self.require_empty_description and material.description.strip():
            return None
        return RuleMatch(
            rule_id=self.id,
            category=self.category,
            weight=self.weight,
            severity=self.severity,
            reason=self.reason,
        )


@dataclass(frozen=True)
class ModerationDecision:
    material_id: str
    risk_score: int
    action: ReviewAction
    matches: list[RuleMatch]

    @property
    def risk_reasons(self) -> list[str]:
        return [match.reason for match in self.matches]

    def to_dict(self) -> dict[str, Any]:
        return {
            "materialId": self.material_id,
            "riskScore": self.risk_score,
            "action": self.action.value,
            "riskReasons": self.risk_reasons,
            "matches": [
                {
                    "ruleId": match.rule_id,
                    "category": match.category,
                    "weight": match.weight,
                    "severity": match.severity,
                    "reason": match.reason,
                }
                for match in self.matches
            ],
        }


class RuleBasedModerationEngine:
    """Weighted rule scorer inspired by open-source rule moderation systems.

    The prototype follows a SpamAssassin-like pattern: evaluate independent rules,
    sum rule weights, and map the final score to a review action. It is isolated
    from production data and deliberately deterministic for regression testing.
    """

    def __init__(
        self,
        rules: list[ModerationRule] | None = None,
        *,
        manual_review_threshold: int = 40,
        reject_threshold: int = 80,
        hide_threshold: int = 100,
    ) -> None:
        self.rules = rules or DEFAULT_RULES
        self.manual_review_threshold = manual_review_threshold
        self.reject_threshold = reject_threshold
        self.hide_threshold = hide_threshold

    def review(self, material: MaterialSample) -> ModerationDecision:
        matches = [match for rule in self.rules if (match := rule.match(material))]
        risk_score = sum(match.weight for match in matches)
        return ModerationDecision(
            material_id=material.id,
            risk_score=risk_score,
            action=self._action_for_score(risk_score, matches),
            matches=matches,
        )

    def review_many(self, materials: list[MaterialSample]) -> list[ModerationDecision]:
        return [self.review(material) for material in materials]

    def _action_for_score(self, risk_score: int, matches: list[RuleMatch]) -> ReviewAction:
        if any(match.severity == "critical" for match in matches) or risk_score >= self.hide_threshold:
            return ReviewAction.HIDE
        if risk_score >= self.reject_threshold:
            return ReviewAction.REJECT
        if risk_score >= self.manual_review_threshold:
            return ReviewAction.MANUAL_REVIEW
        return ReviewAction.APPROVE


def load_material_samples(raw_items: list[dict[str, Any]]) -> list[MaterialSample]:
    return [
        MaterialSample(
            id=str(item["id"]),
            title=str(item.get("title") or ""),
            description=str(item.get("description") or ""),
            filename=str(item.get("filename") or ""),
            price_cents=int(item.get("priceCents") or 0),
            uploader_age_days=int(item.get("uploaderAgeDays") or 0),
            uploader_uploads_24h=int(item.get("uploaderUploads24h") or 0),
            reports_7d=int(item.get("reports7d") or 0),
            duplicate_count=int(item.get("duplicateCount") or 0),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in raw_items
    ]


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)


DEFAULT_RULES: list[ModerationRule] = [
    ModerationRule(
        id="copyright-textbook-scan",
        category="copyright",
        weight=60,
        severity="high",
        reason="疑似教材扫描版或原版受版权保护资料",
        text_patterns=(r"教材.*扫描|扫描.*教材|原版教材|电子书全集",),
        filename_patterns=(r"教材.*扫描|扫描.*教材|原版教材",),
    ),
    ModerationRule(
        id="paid-course-recording",
        category="copyright",
        weight=85,
        severity="high",
        reason="疑似付费课程录屏或机构课程外传",
        text_patterns=(r"付费课|付费课程|录屏|网课全集|机构课程",),
        filename_patterns=(r"paid-course|录屏|网课|机构课程",),
    ),
    ModerationRule(
        id="exam-answer-leak",
        category="academic_integrity",
        weight=75,
        severity="high",
        reason="疑似考试答案、泄题或不当考试材料",
        text_patterns=(r"答案泄露|考试答案|原题答案|保过|押题答案",),
        filename_patterns=(r"答案泄露|考试答案|押题答案",),
    ),
    ModerationRule(
        id="gray-service",
        category="abuse",
        weight=90,
        severity="critical",
        reason="疑似代写、代考、刷课等违规服务",
        text_patterns=(r"代写|代考|刷课|包过|外挂",),
    ),
    ModerationRule(
        id="new-user-burst-upload",
        category="abnormal_behavior",
        weight=35,
        severity="medium",
        reason="新账号短时间大量上传，建议人工复核",
        max_uploader_age_days=7,
        min_uploads_24h=5,
    ),
    ModerationRule(
        id="duplicate-upload",
        category="quality",
        weight=30,
        severity="medium",
        reason="疑似重复资料或批量搬运",
        min_duplicate_count=2,
    ),
    ModerationRule(
        id="reported-content",
        category="community_signal",
        weight=45,
        severity="medium",
        reason="近期举报较多，建议人工复核",
        min_reports_7d=3,
    ),
    ModerationRule(
        id="high-price-empty-description",
        category="quality",
        weight=35,
        severity="medium",
        reason="高价资料缺少有效描述，可能影响质量和合规判断",
        min_price_cents=3000,
        require_empty_description=True,
    ),
]
