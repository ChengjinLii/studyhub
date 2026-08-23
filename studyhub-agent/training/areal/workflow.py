from __future__ import annotations

import json
from pathlib import Path

from studyhub_agent.trajectory.export import export_trajectories
from training.areal.grouped_rollout import GroupedEpisode


def export_grouped_episode(group: GroupedEpisode, artifact_root: str | Path) -> list[Path]:
    """Export grouped rollouts as separate JSONL files for a later trainer process."""

    root = Path(artifact_root).resolve() / "trajectories" / group.group_id.replace(":", "-")
    root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, rollout in enumerate(group.rollouts):
        destination = root / f"rollout-{index:03d}.jsonl"
        temporary = destination.with_suffix(".jsonl.tmp")
        temporary.write_text(
            "".join(
                json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for event in rollout.trajectory
            ),
            encoding="utf-8",
        )
        temporary.replace(destination)
        outputs.append(destination)
    if outputs:
        export_trajectories(outputs, root / "group.jsonl")
    return outputs
