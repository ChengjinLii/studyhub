from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from pydantic import Field, StrictBool, ValidationError

from .schemas import Decision, ReviewRequest, StrictModel
from .service import ReviewService


class EvaluationCase(StrictModel):
    request: ReviewRequest
    expected_risks: dict[str, StrictBool] = Field(min_length=1, max_length=32)
    expected_decision: Decision | None = None


def probability_metrics(samples: list[tuple[float, bool]], threshold: float) -> dict:
    count = len(samples)
    if not count:
        return {"labeled_checks": 0}
    tp = sum(probability >= threshold and target for probability, target in samples)
    fp = sum(probability >= threshold and not target for probability, target in samples)
    fn = sum(probability < threshold and target for probability, target in samples)
    tn = count - tp - fp - fn
    bins = defaultdict(list)
    for probability, target in samples:
        bins[min(9, int(probability * 10))].append((probability, target))
    ece = sum(
        abs(sum(p for p, _ in bucket) / len(bucket) - sum(y for _, y in bucket) / len(bucket))
        * len(bucket)
        / count
        for bucket in bins.values()
    )
    return {
        "labeled_checks": count,
        "risk_threshold": threshold,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "brier_score": sum((probability - target) ** 2 for probability, target in samples) / count,
        "ece_10_bins": ece,
    }


def label_metrics(samples: list[tuple[bool, bool]]) -> dict:
    tp = sum(prediction and target for prediction, target in samples)
    fp = sum(prediction and not target for prediction, target in samples)
    fn = sum(not prediction and target for prediction, target in samples)
    tn = len(samples) - tp - fp - fn
    return {
        "labeled_checks": len(samples),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
    }


def evaluate_file(service: ReviewService, path: Path) -> dict:
    known = {rule.id: rule for rule in service.policy.rules}
    samples = defaultdict(list)
    labels = defaultdict(list)
    eligible_label_cases = 0
    statuses, decisions, models = Counter(), Counter(), set()
    total, decision_labels, decision_correct = 0, 0, 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if total >= 10_000 or len(line) > 24 * 1024 * 1024:
                raise ValueError("evaluation dataset exceeds limits")
            try:
                case = EvaluationCase.model_validate_json(line)
            except ValidationError as exc:
                raise ValueError(f"invalid evaluation case at line {line_number}") from exc
            if set(case.expected_risks) - set(known):
                raise ValueError(f"unknown rule in evaluation case at line {line_number}")
            result = service.review(case.request)
            total += 1
            statuses[result.status] += 1
            decisions[result.decision] += 1
            models.add(result.model)
            if result.status not in {"completed", "partial"}:
                continue
            model_findings = {
                finding.rule_id: finding for finding in result.findings if finding.source == "model"
            }
            for rule_id, target in case.expected_risks.items():
                probability = model_findings[rule_id].risk_probability
                if probability is not None and result.status == "completed":
                    samples[rule_id].append((probability, target))
                finding = model_findings[rule_id]
                if (
                    result.model_assessment is not None
                    and not case.request.content.images
                    and finding.outcome in {"clear", "review", "reject"}
                ):
                    labels[rule_id].append((finding.outcome != "clear", target))
            if result.model_assessment is not None and not case.request.content.images:
                eligible_label_cases += 1
            if case.expected_decision is not None:
                decision_labels += 1
                decision_correct += result.decision == case.expected_decision
    if total == 0:
        raise ValueError("evaluation dataset is empty")
    return {
        "policy_version": service.policy.version,
        "policy_sha256": service.policy.sha256,
        "models": sorted(models),
        "backend": service.backend.name,
        "calibrated_for_studyhub": False,
        "total_cases": total,
        "statuses": dict(statuses),
        "decisions": dict(decisions),
        "eligible_model_cases": statuses["completed"],
        "eligible_label_cases": eligible_label_cases,
        "manual_review_rate": decisions["manual_review"] / total,
        "allow_auto_approve": service.settings.allow_auto_approve,
        "allow_auto_reject": service.settings.allow_auto_reject,
        "decision_accuracy": decision_correct / decision_labels if decision_labels else None,
        "decision_labeled_cases": decision_labels,
        "per_rule": {
            key: probability_metrics(samples[key], rule.review_threshold)
            for key, rule in known.items()
        },
        "per_rule_labels": {key: label_metrics(labels[key]) for key in known},
        "limitations": [
            "Only completed real-backend cases enter model metrics; "
            "demo/degraded cases are excluded.",
            "Native guard categories use separate label metrics, including partial text-only "
            "cases. Unsupported rules and image-containing cases are excluded; "
            "approximate mappings are not calibrated probabilities.",
            "This evaluator reports metrics; it does not train or calibrate a model.",
            "Decision metrics depend on the automatic-decision gates and the chosen labels.",
            "Dataset quality and representativeness require independent human verification.",
        ],
    }
