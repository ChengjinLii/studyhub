"""Register the pre-defined data attribution arms after the core winner is fixed."""

from __future__ import annotations

import argparse
import json
from typing import Literal

from .contract import ControlledPaths
from .registry import register_specs
from .run import resolve_spec
from .variants import router_data_experiments, tutor_mix_experiments


def register_extensions(
    *,
    task: Literal["router", "tutor"],
    experiment_id: str,
    seed: int,
    paths: ControlledPaths | None = None,
) -> dict[str, object]:
    paths = paths or ControlledPaths()
    winner = resolve_spec(paths=paths, experiment_id=experiment_id, seed=seed)
    if winner.task != task:
        raise ValueError(f"winner task is {winner.task}, but extension task is {task}")
    specs = (
        router_data_experiments(winner)
        if task == "router"
        else tutor_mix_experiments(winner)
    )
    registry = register_specs(
        specs,
        paths=paths,
        reason=(
            f"Roadmap controlled-v2 {task} attribution arms from "
            f"{winner.experiment_id}/seed={winner.seed}"
        ),
    )
    return {
        "task": task,
        "parent": winner.to_dict(),
        "registered": [item.to_dict() for item in specs],
        "registry_status": registry.get("status"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("router", "tutor"))
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    result = register_extensions(
        task=args.task,
        experiment_id=args.experiment_id,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
