"""Create the one-time final-holdout evaluation receipt after model selection."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analyze_teacher_hidden_eval import analyze_predictions
from .build_final_holdout_v2 import DEFAULT_HOLDOUT_DATASET, DEFAULT_HOLDOUT_DIR
from .spec import load_jsonl, sha256_file


DEFAULT_PREDICTIONS = DEFAULT_HOLDOUT_DIR / "results/adapter_predictions.jsonl"
DEFAULT_RECEIPT = DEFAULT_HOLDOUT_DIR / "evaluation_receipt.json"


def record_final_evaluation(
    *,
    adapter_path: Path,
    predictions_path: Path = DEFAULT_PREDICTIONS,
    dataset_path: Path = DEFAULT_HOLDOUT_DATASET,
    seal_path: Path = DEFAULT_HOLDOUT_DIR / "seal.json",
    receipt_path: Path = DEFAULT_RECEIPT,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    if receipt_path.exists():
        raise FileExistsError(
            f"final holdout already has an evaluation receipt: {receipt_path}"
        )
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    current_dataset_sha = sha256_file(dataset_path)
    if current_dataset_sha != seal["dataset_sha256"]:
        raise ValueError("final holdout dataset hash no longer matches its seal")
    rows = load_jsonl(predictions_path)
    if len(rows) != int(seal["records"]):
        raise ValueError("final prediction count does not match the sealed holdout")
    if {str(row["split"]) for row in rows} != {"final_holdout_v2"}:
        raise ValueError("predictions are not exclusively from final_holdout_v2")

    adapter_weights = adapter_path / "adapter_model.safetensors"
    if not adapter_weights.is_file():
        raise FileNotFoundError(f"adapter weights not found: {adapter_weights}")
    analysis = analyze_predictions(predictions_path)
    evaluated_at = evaluated_at or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat()
    receipt = {
        "schema_version": "studyhub.agent.router.final_evaluation_receipt.v1",
        "evaluation_count": 1,
        "evaluated_at": evaluated_at,
        "sealed_dataset": {
            "path": str(dataset_path),
            "sha256": current_dataset_sha,
            "seal_sha256": sha256_file(seal_path),
            "records": len(rows),
        },
        "selected_adapter": {
            "path": str(adapter_path),
            "weight_sha256": sha256_file(adapter_weights),
        },
        "predictions": {
            "path": str(predictions_path),
            "sha256": sha256_file(predictions_path),
        },
        "analysis": analysis,
        "policy": {
            "selected_before_final_evaluation": True,
            "repeat_evaluation_allowed": False,
            "production_deployment_implied": False,
        },
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_HOLDOUT_DATASET)
    parser.add_argument(
        "--seal",
        type=Path,
        default=DEFAULT_HOLDOUT_DIR / "seal.json",
    )
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    receipt = record_final_evaluation(
        adapter_path=args.adapter,
        predictions_path=args.predictions,
        dataset_path=args.dataset,
        seal_path=args.seal,
        receipt_path=args.receipt,
    )
    analysis = receipt["analysis"]
    print(
        json.dumps(
            {
                "evaluation_count": receipt["evaluation_count"],
                "overall": analysis["overall"],
                "subset_metrics": analysis["subset_metrics"],
                "safety": analysis["safety"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
