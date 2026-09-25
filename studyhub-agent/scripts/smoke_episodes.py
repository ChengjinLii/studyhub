"""Run fixture tasks against a served model and write Episode JSONL (sub-project 1 acceptance)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from studyhub_agent.contracts.episode import EpisodeSpec
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.runner import EpisodeRunner
from studyhub_agent.runtime.token_client import SGLangGenerateBackend, TokenPolicyClient
from studyhub_agent.runtime.tokenizer import HFTokenizer, token_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--sglang-url", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    tokenizer = HFTokenizer.from_model_dir(args.model_dir)
    revision = f"{args.model_dir.name}@{(args.model_dir / 'tokenizer.json').stat().st_size}"
    runner = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision=revision, count_tokens=token_counter(tokenizer))
    policy = TokenPolicyClient(tokenizer, SGLangGenerateBackend(args.sglang_url))
    environment = ReplayEnvironment(load_snapshot(args.snapshot))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for line in args.tasks.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            episode = runner.run(EpisodeSpec.model_validate_json(line), environment, policy)
            handle.write(episode.model_dump_json() + "\n")
            print(f"{episode.spec.episode_id}: {episode.termination} turns={len(episode.turns)} hash={episode.contract_hash[:19]}")


if __name__ == "__main__":
    main()
