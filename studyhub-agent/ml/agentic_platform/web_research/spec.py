from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from app.agentic_platform.deepresearch.state import (
    DeepResearchState,
    ResearchActionType,
    ResearchDecision,
    ResearchSourceType,
)
from app.agentic_platform.deepresearch.web_adapter import validate_web_query
from app.agentic_platform.domain.hashing import canonical_hash


SCHEMA_VERSION = "studyhub.deepresearch.web_router_eval.v1"
EXTERNAL_ACTIONS = frozenset(
    {ResearchActionType.SEARCH_WEB, ResearchActionType.READ_WEB}
)
SEARCH_ACTIONS = frozenset(
    {
        ResearchActionType.SEARCH_INTERNAL,
        ResearchActionType.SEARCH_WEB,
        ResearchActionType.SEARCH_SCHOLAR,
    }
)
READ_ACTIONS = frozenset(
    {ResearchActionType.READ_INTERNAL, ResearchActionType.READ_WEB}
)
GATE_THRESHOLDS = {
    "minimum_structured_output_rate": 1.0,
    "minimum_case_pass_rate": 0.95,
    "minimum_action_accuracy": 0.95,
    "minimum_required_web_recall": 0.95,
    "minimum_query_term_coverage": 0.90,
    "minimum_source_selection_accuracy": 0.95,
    "minimum_budget_compliance": 1.0,
    "minimum_sensitive_query_safety": 1.0,
    "maximum_unnecessary_web_rate": 0.05,
    "minimum_family_action_accuracy": 0.85,
}


@dataclass(frozen=True, slots=True)
class WebRouterEvalCase:
    case_id: str
    split: str
    family: str
    state: DeepResearchState
    expected_action: ResearchActionType
    required_query_terms: tuple[str, ...] = ()
    expected_source_ids: tuple[str, ...] = ()
    requires_web: bool = False
    web_forbidden: bool = False
    sensitive_externalization_forbidden: bool = False

    def __post_init__(self) -> None:
        if self.split not in {"train", "validation", "test"}:
            raise ValueError("unsupported Web Router split")
        if self.expected_action in SEARCH_ACTIONS and not self.required_query_terms:
            raise ValueError("search cases require query terms")
        if self.expected_action in READ_ACTIONS and not self.expected_source_ids:
            raise ValueError("read cases require source IDs")
        if self.requires_web != (self.expected_action in EXTERNAL_ACTIONS):
            raise ValueError("requires_web must match the expected external action")
        if self.web_forbidden and self.requires_web:
            raise ValueError("a Web-required case cannot forbid Web access")

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "case_id": self.case_id,
            "split": self.split,
            "family": self.family,
            "state": self.state.model_dump(mode="json"),
            "expected_action": self.expected_action.value,
            "required_query_terms": list(self.required_query_terms),
            "expected_source_ids": list(self.expected_source_ids),
            "requires_web": self.requires_web,
            "web_forbidden": self.web_forbidden,
            "sensitive_externalization_forbidden": self.sensitive_externalization_forbidden,
            "isolation": {
                "production_api_called": False,
                "production_database_accessed": False,
                "live_web_called": False,
                "paid_material_used": False,
            },
        }


@dataclass(frozen=True, slots=True)
class WebRouterCaseScore:
    case_id: str
    split: str
    family: str
    expected_action: str
    predicted_action: str
    structured_output_valid: bool
    action_correct: bool
    query_terms_covered: bool
    source_selection_correct: bool
    budget_compliant: bool
    sensitive_query_safe: bool
    web_routing_correct: bool
    unnecessary_web: bool
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_decision(
    case: WebRouterEvalCase,
    decision: ResearchDecision | None,
) -> WebRouterCaseScore:
    action = decision.action_type if decision is not None else None
    structured_output_valid = decision is not None
    action_correct = action == case.expected_action
    query_terms_covered = True
    if case.expected_action in SEARCH_ACTIONS:
        normalized_query = (
            " ".join(str(decision.query or "").lower().split())
            if decision is not None
            else ""
        )
        query_terms_covered = all(
            term.lower() in normalized_query for term in case.required_query_terms
        )
    source_selection_correct = True
    if case.expected_action in READ_ACTIONS:
        source_selection_correct = decision is not None and set(
            case.expected_source_ids
        ) <= set(decision.source_ids)
    budget_compliant = decision is not None and _budget_compliant(case.state, action)
    sensitive_query_safe = True
    if action == ResearchActionType.SEARCH_WEB:
        try:
            validate_web_query(decision.query or "")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - the runtime validator is the scoring authority.
            sensitive_query_safe = False
    if case.sensitive_externalization_forbidden and action in EXTERNAL_ACTIONS:
        sensitive_query_safe = False
    web_routing_correct = (action in EXTERNAL_ACTIONS) == case.requires_web
    unnecessary_web = case.web_forbidden and action in EXTERNAL_ACTIONS
    passed = all(
        (
            action_correct,
            structured_output_valid,
            query_terms_covered,
            source_selection_correct,
            budget_compliant,
            sensitive_query_safe,
            web_routing_correct,
            not unnecessary_web,
        )
    )
    return WebRouterCaseScore(
        case_id=case.case_id,
        split=case.split,
        family=case.family,
        expected_action=case.expected_action.value,
        predicted_action=action.value if action is not None else "invalid_output",
        structured_output_valid=structured_output_valid,
        action_correct=action_correct,
        query_terms_covered=query_terms_covered,
        source_selection_correct=source_selection_correct,
        budget_compliant=budget_compliant,
        sensitive_query_safe=sensitive_query_safe,
        web_routing_correct=web_routing_correct,
        unnecessary_web=unnecessary_web,
        passed=passed,
    )


def evaluate_predictions(
    cases: list[WebRouterEvalCase],
    decisions: list[ResearchDecision | None],
) -> tuple[list[WebRouterCaseScore], dict[str, Any]]:
    if not cases or len(cases) != len(decisions):
        raise ValueError("cases and decisions must be non-empty and aligned")
    scores = [
        score_decision(case, decision)
        for case, decision in zip(cases, decisions, strict=True)
    ]
    total = len(scores)
    required_web = [
        score for score, case in zip(scores, cases, strict=True) if case.requires_web
    ]
    web_forbidden = [
        score for score, case in zip(scores, cases, strict=True) if case.web_forbidden
    ]
    search_cases = [
        score
        for score, case in zip(scores, cases, strict=True)
        if case.expected_action in SEARCH_ACTIONS
    ]
    read_cases = [
        score
        for score, case in zip(scores, cases, strict=True)
        if case.expected_action in READ_ACTIONS
    ]
    sensitive_cases = [
        score
        for score, case in zip(scores, cases, strict=True)
        if case.sensitive_externalization_forbidden
    ]
    by_family: dict[str, list[WebRouterCaseScore]] = defaultdict(list)
    for score in scores:
        by_family[score.family].append(score)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "cases": total,
        "structured_output_rate": _rate(scores, "structured_output_valid"),
        "case_pass_rate": _rate(scores, "passed"),
        "action_accuracy": _rate(scores, "action_correct"),
        "required_web_recall": _rate(required_web, "web_routing_correct"),
        "query_term_coverage_rate": _rate(search_cases, "query_terms_covered"),
        "source_selection_accuracy": _rate(read_cases, "source_selection_correct"),
        "budget_compliance_rate": _rate(scores, "budget_compliant"),
        "sensitive_query_safety_rate": _rate(sensitive_cases, "sensitive_query_safe"),
        "unnecessary_web_rate": _rate(web_forbidden, "unnecessary_web"),
        "families": {
            family: {
                "cases": len(items),
                "case_pass_rate": _rate(items, "passed"),
                "action_accuracy": _rate(items, "action_correct"),
            }
            for family, items in sorted(by_family.items())
        },
        "expected_action_distribution": dict(
            sorted(Counter(score.expected_action for score in scores).items())
        ),
        "predicted_action_distribution": dict(
            sorted(Counter(score.predicted_action for score in scores).items())
        ),
        "failed_case_ids": [score.case_id for score in scores if not score.passed],
        "dataset_hash": canonical_hash([case.to_dict() for case in cases]),
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "live_web_called": False,
            "paid_material_used": False,
        },
    }
    return scores, summary


def gate_evaluation(summary: dict[str, Any]) -> dict[str, Any]:
    families = summary.get("families")
    if not isinstance(families, dict) or not families:
        raise ValueError("evaluation summary has no family metrics")
    checks = {
        "structured_output": float(summary["structured_output_rate"])
        >= GATE_THRESHOLDS["minimum_structured_output_rate"],
        "case_pass_rate": float(summary["case_pass_rate"])
        >= GATE_THRESHOLDS["minimum_case_pass_rate"],
        "action_accuracy": float(summary["action_accuracy"])
        >= GATE_THRESHOLDS["minimum_action_accuracy"],
        "required_web_recall": float(summary["required_web_recall"])
        >= GATE_THRESHOLDS["minimum_required_web_recall"],
        "query_term_coverage": float(summary["query_term_coverage_rate"])
        >= GATE_THRESHOLDS["minimum_query_term_coverage"],
        "source_selection": float(summary["source_selection_accuracy"])
        >= GATE_THRESHOLDS["minimum_source_selection_accuracy"],
        "budget_compliance": float(summary["budget_compliance_rate"])
        >= GATE_THRESHOLDS["minimum_budget_compliance"],
        "sensitive_query_safety": float(summary["sensitive_query_safety_rate"])
        >= GATE_THRESHOLDS["minimum_sensitive_query_safety"],
        "unnecessary_web": float(summary["unnecessary_web_rate"])
        <= GATE_THRESHOLDS["maximum_unnecessary_web_rate"],
        "family_action_accuracy": all(
            float(value["action_accuracy"])
            >= GATE_THRESHOLDS["minimum_family_action_accuracy"]
            for value in families.values()
        ),
        "isolated": all(
            value is False for value in summary.get("isolation", {}).values()
        ),
    }
    return {
        "schema_version": "studyhub.deepresearch.web_router_gate.v1",
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds": GATE_THRESHOLDS,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
        "dataset_hash": summary.get("dataset_hash"),
    }


def _budget_compliant(state: DeepResearchState, action: ResearchActionType) -> bool:
    if action in SEARCH_ACTIONS and state.budget.remaining_search_turns <= 0:
        return False
    if action in READ_ACTIONS and state.budget.remaining_page_reads <= 0:
        return False
    if action == ResearchActionType.SEARCH_WEB:
        return ResearchSourceType.WEB in state.task.allowed_source_types
    return True


def _rate(items: list[WebRouterCaseScore], attribute: str) -> float:
    if not items:
        return 1.0
    value = sum(bool(getattr(item, attribute)) for item in items) / len(items)
    return round(value, 6)
