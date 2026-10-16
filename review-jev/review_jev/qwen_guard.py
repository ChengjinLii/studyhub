from __future__ import annotations

import re
import threading
from typing import get_args

from .backends import BackendUnavailable, DecisionResult, resolve_device
from .config import Settings
from .policy import Policy
from .schemas import Finding, GuardCategory, GuardScore, ModelAssessment
from .scoring import softmax

CATEGORIES = set(get_args(GuardCategory))
RULE_CATEGORIES = {
    "sexual_content": {"Sexual Content or Sexual Acts"},
    "graphic_violence": {"Violent"},
    "hate_harassment": {"Unethical Acts"},
    "illegal_harm": {"Non-violent Illegal Acts", "Suicide & Self-Harm"},
    "sensitive_personal_data": {"PII"},
    "review_manipulation": {"Jailbreak"},
}
ASSESSMENT_PATTERN = r"\s*Safety:\s*(Safe|Controversial|Unsafe)\s*\nCategories:\s*([^\n]+)\s*"


def parse_assessment(output: str) -> ModelAssessment:
    # Only accept the guard's native labels, never arbitrary generated explanations.
    match = re.fullmatch(ASSESSMENT_PATTERN, output)
    if not match:
        raise ValueError("invalid guard response")
    severity, labels = match.groups()
    categories = [item.strip() for item in labels.strip().split(",")]
    if categories == ["None"]:
        categories = []
    if set(categories) - CATEGORIES:
        raise ValueError("unknown guard category")
    return ModelAssessment(safety=severity, categories=categories)


LABELS = ("Safe", "Controversial", "Unsafe")


def candidate_log_scores(model, tokenizer, prompt: str, limit: int) -> tuple[dict, int]:
    import torch
    import torch.nn.functional as F

    prefix = tokenizer(prompt + "Safety:", add_special_tokens=False, return_tensors="pt")
    prefix_ids = prefix["input_ids"].to(model.device)
    scores, input_tokens = {}, 0
    for label in LABELS:
        # Include the label terminator and sum every candidate token, not only the first.
        candidate = tokenizer(" " + label + "\n", add_special_tokens=False, return_tensors="pt")[
            "input_ids"
        ].to(model.device)
        count = candidate.shape[-1]
        full = torch.cat([prefix_ids, candidate], dim=-1)
        if count == 0 or full.shape[-1] > limit:
            raise BackendUnavailable("qwen_input_limit_exceeded")
        output = model(
            input_ids=full,
            attention_mask=torch.ones_like(full),
            use_cache=False,
            logits_to_keep=count + 1,
        )
        logits = output.logits[0, -count - 1 : -1].float()
        log_probs = F.log_softmax(logits, dim=-1)
        scores[label] = float(log_probs.gather(-1, candidate[0, :, None]).sum().item())
        input_tokens += full.shape[-1]
    return scores, input_tokens


def guard_findings(assessment: ModelAssessment, policy: Policy, has_images: bool) -> list[Finding]:
    categories = set(assessment.categories)
    findings = []
    for rule in policy.rules:
        mapped = RULE_CATEGORIES.get(rule.id)
        if mapped is None:
            outcome = "unavailable"
            reason = "Qwen3Guard does not evaluate this custom StudyHub rule."
            evidence = []
        else:
            evidence = sorted(categories & mapped)
            # Native taxonomy is broader than StudyHub's rules; signals require review.
            outcome = "review" if evidence else "clear"
            reason = (
                "Native guard category suggests a text risk; mapping is approximate."
                if evidence
                else "No corresponding native category reported for text; "
                "not proof of compliance with the custom StudyHub policy."
            )
        findings.append(
            Finding(
                rule_id=rule.id,
                category=rule.category,
                source="model",
                scope="text",
                outcome=outcome,
                reason=reason,
                evidence=evidence,
            )
        )
    findings.append(
        Finding(
            rule_id="guard_safety",
            category="compliance",
            source="model",
            scope="text",
            outcome="clear" if assessment.safety == "Safe" and not categories else "review",
            reason=f"Native Qwen3Guard text safety label: {assessment.safety}.",
            evidence=assessment.categories,
        )
    )
    if "Copyright Violation" in categories:
        findings.append(
            Finding(
                rule_id="guard_copyright_risk",
                category="copyright",
                source="model",
                scope="text",
                outcome="review",
                reason="Native copyright risk label; sharing rights are unverified.",
                evidence=["Copyright Violation"],
            )
        )
    if has_images:
        findings.append(
            Finding(
                rule_id="image_moderation",
                category="compliance",
                source="model",
                outcome="unavailable",
                reason="Qwen3Guard is text-only; submitted pixels were not read.",
            )
        )
    return findings


class Qwen3GuardBackend:
    name = "qwen3guard"
    demo = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.tokenizer = None
        self.lock = threading.Lock()

    def _load(self):
        if self.model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            kwargs = {"revision": self.settings.model_revision, "trust_remote_code": False}
            device = resolve_device(self.settings.device)
            tokenizer = AutoTokenizer.from_pretrained(self.settings.model, **kwargs)
            model = (
                AutoModelForCausalLM.from_pretrained(
                    self.settings.model,
                    dtype=torch.float32 if device == "cpu" else "auto",
                    **kwargs,
                )
                .to(device)
                .eval()
            )
            self.tokenizer, self.model = tokenizer, model

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult:
        submission = state.get("untrusted_submission", {})
        text = "\n\n".join(f"{key}:\n{value}" for key, value in submission.items() if value)
        if not text:
            raise BackendUnavailable("text_only_backend_no_text")
        try:
            import torch

            with self.lock:
                self._load()
                # Keep the official policy template; submitted text is not a policy override.
                prompt = self.tokenizer.apply_chat_template(
                    [{"role": "user", "content": text}],
                    tokenize=False,
                )
                inputs = self.tokenizer(prompt, return_tensors="pt", truncation=False)
                input_tokens = inputs["input_ids"].shape[-1]
                if input_tokens > self.settings.max_input_tokens:
                    raise BackendUnavailable("qwen_input_limit_exceeded")
                inputs = inputs.to(self.model.device)
                with torch.inference_mode():
                    log_scores, scoring_tokens = candidate_log_scores(
                        self.model, self.tokenizer, prompt, self.settings.max_input_tokens
                    )
                    output = self.model.generate(
                        **inputs,
                        max_new_tokens=128,
                        do_sample=False,
                        max_time=self.settings.timeout_seconds,
                        pad_token_id=self.tokenizer.eos_token_id,
                    )
                tokens = output[0][input_tokens:]
                decoded = self.tokenizer.decode(tokens, skip_special_tokens=True)
                assessment = parse_assessment(decoded)
                score = GuardScore(
                    model=self.settings.model,
                    model_revision=self.settings.model_revision,
                    modality="text",
                    input_id="submission",
                    policy_id="text_safety",
                    task_type="multiclass",
                    scoring_method="teacher_forced_sequence",
                    log_scores=log_scores,
                    probabilities=softmax(log_scores, self.settings.text_temperature),
                    temperature=self.settings.text_temperature,
                )
                return DecisionResult(
                    self.settings.model,
                    {},
                    {"input_tokens": input_tokens + scoring_tokens, "output_tokens": len(tokens)},
                    assessment,
                    model_revision=self.settings.model_revision,
                    scores=[score],
                )
        except BackendUnavailable:
            raise
        except Exception as exc:
            raise BackendUnavailable("qwen_model_unavailable_or_invalid_response") from exc

    def ready(self) -> bool:
        return self.model is not None

    def close(self) -> None:
        with self.lock:
            self.model, self.tokenizer = None, None
