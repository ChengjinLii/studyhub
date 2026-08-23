from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from studyhub_agent.trajectory.recorder import read_trajectory


def export_trajectories(inputs: Iterable[str | Path], output: str | Path) -> Path:
    """Merge validated trajectories without inventing derived training labels."""

    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for source in inputs:
            for event in read_trajectory(source):
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(destination)
    return destination
