from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from typing import Protocol

from app.agentic_platform.deepresearch.policy import ModelResearchPolicy
from app.agentic_platform.deepresearch.state import DeepResearchState, ResearchDecision
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json
from app.agentic_platform.policy.openai_compatible_provider import (
    OpenAICompatibleProvider,
)

from .dataset import build_web_router_eval_cases
from .policy import DeterministicWebRouterPolicy
from .spec import WebRouterEvalCase, evaluate_predictions, gate_evaluation


class WebRouterPolicy(Protocol):
    async def decide(self, state: DeepResearchState) -> ResearchDecision: ...


class ModelWebRouterPolicy:
    def __init__(self, policy: ModelResearchPolicy) -> None:
        self.policy = policy

    async def decide(self, state: DeepResearchState) -> ResearchDecision:
        turn = await self.policy.decide(state)
        return turn.parsed_output


async def evaluate_policy(
    policy: WebRouterPolicy,
    cases: list[WebRouterEvalCase],
    *,
    concurrency: int = 1,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    semaphore = asyncio.Semaphore(concurrency)

    async def predict(
        case: WebRouterEvalCase,
    ) -> tuple[ResearchDecision | None, dict[str, object]]:
        async with semaphore:
            try:
                return await policy.decide(case.state), {}
            except Exception as exc:  # noqa: BLE001 - one malformed output must not discard the frozen run.
                return None, {"prediction_error_type": _safe_error_type(exc)}

    predictions = await asyncio.gather(*(predict(case) for case in cases))
    decisions = [decision for decision, _diagnostics in predictions]
    diagnostics = [item for _decision, item in predictions]
    return _evaluate_decisions(cases, decisions, diagnostics=diagnostics)


def _evaluate_decisions(
    cases: list[WebRouterEvalCase],
    decisions: list[ResearchDecision | None],
    *,
    diagnostics: list[dict[str, object]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    diagnostics = diagnostics or [{} for _case in cases]
    if len(cases) != len(decisions) or len(cases) != len(diagnostics):
        raise ValueError("Web Router predictions and diagnostics must align with cases")
    scores, summary = evaluate_predictions(cases, decisions)
    rows = [
        {
            "case_id": case.case_id,
            "split": case.split,
            "family": case.family,
            "state_hash": canonical_hash(case.state),
            "decision": decision.model_dump(mode="json")
            if decision is not None
            else None,
            **diagnostic,
            "score": score.to_dict(),
        }
        for case, decision, diagnostic, score in zip(
            cases, decisions, diagnostics, scores, strict=True
        )
    ]
    summary["prediction_error_distribution"] = dict(
        sorted(
            Counter(
                str(item["prediction_error_type"])
                for item in diagnostics
                if item.get("prediction_error_type")
            ).items()
        )
    )
    return rows, summary, gate_evaluation(summary)


def run_evaluation(
    *,
    policy_name: str,
    split: str,
    output_dir: Path,
    concurrency: int,
    model_base_url: str | None = None,
    model_api_key: str | None = None,
    model_id: str | None = None,
    local_model_path: Path | None = None,
    local_adapter_path: Path | None = None,
    local_batch_size: int = 4,
    local_max_new_tokens: int = 512,
    local_device: str = "cuda",
) -> dict[str, object]:
    cases = build_web_router_eval_cases()
    if split != "all":
        cases = [case for case in cases if case.split == split]
    if not cases:
        raise ValueError("Web Router evaluation selection is empty")
    if policy_name == "rule":
        policy: WebRouterPolicy = DeterministicWebRouterPolicy()
        policy_metadata = {
            "name": "deterministic_rule",
            "version": DeterministicWebRouterPolicy.policy_version,
            "teacher_model_api_called": False,
        }
    elif policy_name == "openai-compatible":
        if not all(
            isinstance(value, str) and value.strip()
            for value in (model_base_url, model_api_key, model_id)
        ):
            raise ValueError(
                "openai-compatible evaluation requires model base URL, API key, and model ID"
            )
        provider = OpenAICompatibleProvider(
            base_url=str(model_base_url),
            api_key=str(model_api_key),
            model_id=str(model_id),
            timeout_seconds=45.0,
            max_retries=2,
        )
        policy = ModelWebRouterPolicy(
            ModelResearchPolicy(provider, token_budget=12_000)
        )
        policy_metadata = {
            "name": "openai_compatible",
            "model_id": model_id,
            "base_url_hash": canonical_hash(str(model_base_url).rstrip("/")),
            "teacher_model_api_called": True,
        }
    elif policy_name == "local-hf":
        if local_model_path is None:
            raise ValueError("local-hf evaluation requires a local model path")
        from .local_policy import generate_local_predictions

        local_predictions, local_runtime = generate_local_predictions(
            [case.state for case in cases],
            model_path=local_model_path,
            adapter_path=local_adapter_path,
            batch_size=local_batch_size,
            max_new_tokens=local_max_new_tokens,
            device=local_device,
        )
        rows, summary, gate = _evaluate_decisions(
            cases,
            [item.decision for item in local_predictions],
            diagnostics=[
                {
                    "raw_generated": item.raw_generated,
                    "prediction_error_type": item.error_type,
                    "completion_tokens": item.completion_tokens,
                    "hit_decode_limit": item.hit_decode_limit,
                }
                for item in local_predictions
            ],
        )
        policy_metadata = {
            "name": "local_huggingface",
            "model_path": str(local_model_path.resolve()),
            "adapter_path": str(local_adapter_path.resolve())
            if local_adapter_path is not None
            else None,
            "teacher_model_api_called": False,
            "runtime": local_runtime,
        }
    else:
        raise ValueError("unsupported Web Router policy")

    if policy_name != "local-hf":
        rows, summary, gate = asyncio.run(
            evaluate_policy(policy, cases, concurrency=concurrency)
        )
    output_dir.mkdir(parents=True, exist_ok=False)
    predictions_path = output_dir / "predictions.jsonl"
    predictions_path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8"
    )
    manifest = {
        "schema_version": "studyhub.deepresearch.web_router_eval_manifest.v1",
        "policy": policy_metadata,
        "selection": {
            "split": split,
            "cases": len(cases),
            "split_distribution": dict(
                sorted(Counter(case.split for case in cases).items())
            ),
            "family_distribution": dict(
                sorted(Counter(case.family for case in cases).items())
            ),
        },
        "dataset_hash": summary["dataset_hash"],
        "predictions_hash": canonical_hash(rows),
        "isolation": summary["isolation"],
    }
    summary = {
        **summary,
        "policy": policy_metadata,
        "predictions_path": str(predictions_path.resolve()),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "gate.json").write_text(
        json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"manifest": manifest, "summary": summary, "gate": gate}


def _safe_error_type(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code and len(code) <= 128:
        return code
    return type(exc).__name__


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate Web-enabled DeepResearch routing on frozen states."
    )
    parser.add_argument(
        "--policy", choices=("rule", "openai-compatible", "local-hf"), default="rule"
    )
    parser.add_argument(
        "--split", choices=("all", "train", "validation", "test"), default="validation"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--model-base-url", default=os.getenv("STUDYHUB_WEB_ROUTER_EVAL_MODEL_BASE_URL")
    )
    parser.add_argument(
        "--model-id", default=os.getenv("STUDYHUB_WEB_ROUTER_EVAL_MODEL_ID")
    )
    parser.add_argument("--local-model", type=Path)
    parser.add_argument("--local-adapter", type=Path)
    parser.add_argument("--local-batch-size", type=int, default=4)
    parser.add_argument("--local-max-new-tokens", type=int, default=512)
    parser.add_argument("--local-device", default="cuda")
    args = parser.parse_args()
    result = run_evaluation(
        policy_name=args.policy,
        split=args.split,
        output_dir=args.output_dir,
        concurrency=args.concurrency,
        model_base_url=args.model_base_url,
        model_api_key=os.getenv("STUDYHUB_WEB_ROUTER_EVAL_API_KEY"),
        model_id=args.model_id,
        local_model_path=args.local_model,
        local_adapter_path=args.local_adapter,
        local_batch_size=args.local_batch_size,
        local_max_new_tokens=args.local_max_new_tokens,
        local_device=args.local_device,
    )
    print(
        canonical_json(
            {"output_dir": str(args.output_dir.resolve()), "gate": result["gate"]}
        )
    )
    if not result["gate"]["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()


__all__ = ["ModelWebRouterPolicy", "evaluate_policy", "run_evaluation"]
