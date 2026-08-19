"""One-shot Test and Sealed evaluation for a frozen offline Router candidate."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .evaluate import evaluate_policy
from .gate import assess_locked_split, paired_bootstrap


def assert_locked_evaluation_allowed(
    *,
    split: str,
    frozen_manifest: dict[str, Any],
    frozen_manifest_path: Path,
    acceptance_path: Path,
    access_marker_path: Path,
    prior_test_gate_path: Path | None = None,
) -> None:
    if split not in {"test", "sealed"}:
        raise ValueError("one-shot evaluation supports only test or sealed")
    if access_marker_path.exists():
        raise FileExistsError(f"{split} has already been consumed: {access_marker_path}")
    if frozen_manifest.get("status") != "frozen_before_test":
        raise ValueError("candidate was not frozen before Test")
    if frozen_manifest.get("test_read") is not False or frozen_manifest.get("sealed_read") is not False:
        raise ValueError("frozen manifest already records locked-split access")
    if frozen_manifest.get("acceptance_sha256") != sha256_file(acceptance_path):
        raise ValueError("preregistered acceptance criteria changed after candidate freeze")
    if not frozen_manifest_path.is_file():
        raise FileNotFoundError(frozen_manifest_path)
    if split == "sealed":
        if prior_test_gate_path is None or not prior_test_gate_path.is_file():
            raise ValueError("Sealed requires a completed Test Gate")
        test_gate = _read_json(prior_test_gate_path)
        if test_gate.get("split") != "test" or test_gate.get("passed") is not True:
            raise ValueError("Sealed cannot be authorized before the Test Gate passes")
        if test_gate.get("candidate_manifest_sha256") != sha256_file(frozen_manifest_path):
            raise ValueError("Test Gate and frozen candidate hash differ")


def run_locked_evaluation(
    *,
    split: str,
    model_path: Path,
    dataset_path: Path,
    frozen_manifest_path: Path,
    acceptance_path: Path,
    output_root: Path,
    device: str,
    prior_test_gate_path: Path | None = None,
) -> dict[str, Any]:
    frozen = _read_json(frozen_manifest_path)
    access_marker = output_root / f"{split}_access.json"
    assert_locked_evaluation_allowed(
        split=split,
        frozen_manifest=frozen,
        frozen_manifest_path=frozen_manifest_path,
        acceptance_path=acceptance_path,
        access_marker_path=access_marker,
        prior_test_gate_path=prior_test_gate_path,
    )
    adapter_path = Path(str(frozen["adapter_path"])).resolve()
    adapter_weights = adapter_path / "adapter_model.safetensors"
    if not adapter_weights.is_file():
        raise FileNotFoundError(adapter_weights)
    if sha256_file(adapter_weights) != frozen["adapter_sha256"]:
        raise ValueError("frozen candidate adapter hash changed")
    marker = {
        "schema_version": "studyhub.agent.router_rl.locked_access.v2",
        "split": split,
        "status": "started_and_irrevocably_consumed",
        "started_at": datetime.now(UTC).isoformat(),
        "evaluation_runs": 1,
        "candidate_manifest_sha256": sha256_file(frozen_manifest_path),
        "acceptance_sha256": sha256_file(acceptance_path),
        "dataset_sha256": sha256_file(dataset_path),
        "adapter_sha256": frozen["adapter_sha256"],
        "production_access": False,
    }
    _write_json_exclusive(access_marker, marker)

    baseline_dir = output_root / split / "baseline_sft"
    candidate_dir = output_root / split / "frozen_candidate"
    allow_test = split == "test"
    allow_sealed = split == "sealed"
    try:
        baseline = evaluate_policy(
            model_path=model_path,
            adapter_path=None,
            dataset_path=dataset_path,
            split=split,
            output_dir=baseline_dir,
            device=device,
            max_prompt_tokens=4096,
            action_temperature=1.0,
            seed=26_081_201,
            allow_test=allow_test,
            allow_sealed=allow_sealed,
        )
        candidate = evaluate_policy(
            model_path=model_path,
            adapter_path=adapter_path,
            dataset_path=dataset_path,
            split=split,
            output_dir=candidate_dir,
            device=device,
            max_prompt_tokens=4096,
            action_temperature=1.0,
            seed=26_081_201,
            allow_test=allow_test,
            allow_sealed=allow_sealed,
        )
        if candidate["adapter_sha256"] != frozen["adapter_sha256"]:
            raise RuntimeError("evaluated adapter differs from the frozen candidate")
        statistics_result = paired_bootstrap(
            Path(baseline["predictions_path"]),
            Path(candidate["predictions_path"]),
        )
        assessment = assess_locked_split(
            baseline=baseline,
            candidate=candidate,
            statistics_result=statistics_result,
            split=split,
        )
        result = {
            "schema_version": "studyhub.agent.router_rl.locked_gate.v2",
            **assessment,
            "candidate_manifest_sha256": sha256_file(frozen_manifest_path),
            "acceptance_sha256": sha256_file(acceptance_path),
            "dataset_sha256": sha256_file(dataset_path),
            "baseline_summary_path": str((baseline_dir / "summary.json").resolve()),
            "baseline_summary_sha256": sha256_file(baseline_dir / "summary.json"),
            "candidate_summary_path": str((candidate_dir / "summary.json").resolve()),
            "candidate_summary_sha256": sha256_file(candidate_dir / "summary.json"),
            "access_marker_path": str(access_marker.resolve()),
            "single_pass": True,
            "production_access": False,
        }
        gate_path = output_root / f"{split}_gate.json"
        _write_json_exclusive(gate_path, result)
        marker.update(
            {
                "status": "completed_pass" if result["passed"] else "completed_fail",
                "completed_at": datetime.now(UTC).isoformat(),
                "gate_path": str(gate_path.resolve()),
                "gate_sha256": sha256_file(gate_path),
            }
        )
        _write_json(access_marker, marker)
        return result
    except Exception as exc:
        marker.update(
            {
                "status": "consumed_with_error",
                "failed_at": datetime.now(UTC).isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        _write_json(access_marker, marker)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("test", "sealed"), required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--prior-test-gate", type=Path)
    args = parser.parse_args()
    result = run_locked_evaluation(
        split=args.split,
        model_path=args.model.resolve(),
        dataset_path=args.dataset.resolve(),
        frozen_manifest_path=args.frozen_manifest.resolve(),
        acceptance_path=args.acceptance.resolve(),
        output_root=args.output_root.resolve(),
        device=args.device,
        prior_test_gate_path=(
            args.prior_test_gate.resolve() if args.prior_test_gate else None
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
