"""Run fixture tasks with one of the five shared-loop architectures and write Episode JSONL."""

from __future__ import annotations

import argparse
from pathlib import Path

from studyhub_agent.architectures import (
    CascadeArchitecture,
    PlanExecuteArchitecture,
    ReactArchitecture,
    ReactContextArchitecture,
    ReactVerifyArchitecture,
)
from studyhub_agent.contracts.architecture import Architecture
from studyhub_agent.contracts.episode import EpisodeSpec
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.runner import EpisodeRunner
from studyhub_agent.runtime.token_client import SGLangGenerateBackend, TokenPolicyClient
from studyhub_agent.runtime.tokenizer import HFTokenizer, token_counter


def _architecture(args: argparse.Namespace) -> Architecture:
    if args.architecture == "react_verify":
        return ReactVerifyArchitecture(max_rejections=args.max_citation_rejections)
    if args.architecture == "plan_execute":
        return PlanExecuteArchitecture(max_plan_chars=args.max_plan_chars)
    if args.architecture == "react_context":
        return ReactContextArchitecture(
            context_threshold=args.context_threshold,
            keep_recent_tools=args.keep_recent_tools,
            max_text_chars=args.max_text_chars,
        )
    if args.architecture == "cascade":
        return CascadeArchitecture(escalate_ratio=args.escalate_ratio, max_rejections=args.max_citation_rejections)
    return ReactArchitecture()


def _validated_args(parser: argparse.ArgumentParser, argv: list[str] | None = None) -> argparse.Namespace:
    args = parser.parse_args(argv)
    if args.max_citation_rejections < 0:
        parser.error("--max-citation-rejections must be non-negative")
    try:
        _architecture(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.architecture == "cascade":
        if args.large_model_dir is None or args.large_sglang_url is None:
            parser.error("cascade requires --large-model-dir and --large-sglang-url")
    elif any(value is not None for value in (args.large_model_dir, args.large_sglang_url, args.large_model_id)):
        parser.error("--large-model-* and --large-sglang-url are only used with --architecture cascade")
    for flag, path in (("--model-dir", args.model_dir), ("--large-model-dir", args.large_model_dir)):
        if path is not None and not (path / "tokenizer.json").is_file():
            parser.error(f"{flag} {path} has no tokenizer.json")
    if not args.snapshot.is_file():
        parser.error(f"--snapshot {args.snapshot} does not exist")
    if not args.tasks.is_file():
        parser.error(f"--tasks {args.tasks} does not exist")
    return args


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--sglang-url", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--architecture", choices=("react", "react_verify", "plan_execute", "react_context", "cascade"), default="react"
    )
    parser.add_argument("--max-citation-rejections", type=int, default=2)
    parser.add_argument("--model-id", help="Model identity to record; defaults to the model directory name")
    parser.add_argument("--max-plan-chars", type=int, default=400)
    parser.add_argument("--context-threshold", type=float, default=0.5)
    parser.add_argument("--keep-recent-tools", type=int, default=2)
    parser.add_argument("--max-text-chars", type=int, default=120)
    parser.add_argument("--escalate-ratio", type=float, default=0.7)
    parser.add_argument("--large-model-dir", type=Path)
    parser.add_argument("--large-sglang-url")
    parser.add_argument("--large-model-id")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _validated_args(_parser(), argv)

    tokenizer = HFTokenizer.from_model_dir(args.model_dir)
    runner = EpisodeRunner(
        prompts=DEFAULT_PROMPTS,
        tokenizer_revision=tokenizer.revision,
        count_tokens=token_counter(tokenizer),
    )
    tokenizers = {"small": tokenizer}
    policies = {"small": TokenPolicyClient(tokenizer, SGLangGenerateBackend(args.sglang_url))}
    models = {"small": args.model_id or args.model_dir.name}
    if args.architecture == "cascade":
        large_tokenizer = HFTokenizer.from_model_dir(args.large_model_dir)
        tokenizers["large"] = large_tokenizer
        policies["large"] = TokenPolicyClient(large_tokenizer, SGLangGenerateBackend(args.large_sglang_url))
        models["large"] = args.large_model_id or args.large_model_dir.name
    environment = ReplayEnvironment(load_snapshot(args.snapshot))
    architecture = _architecture(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for line in args.tasks.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            episode = runner.run(
                EpisodeSpec.model_validate_json(line),
                environment,
                policies["small"],
                architecture=architecture,
                policies=policies,
                models=models,
                model_revisions={key: tokenizer.revision for key, tokenizer in tokenizers.items()},
                token_counters={key: token_counter(tokenizer) for key, tokenizer in tokenizers.items()},
            )
            handle.write(episode.model_dump_json() + "\n")
            print(
                f"{episode.spec.episode_id}: {episode.termination} "
                f"architecture={episode.architecture} turns={len(episode.turns)} hash={episode.contract_hash[:19]}"
            )


if __name__ == "__main__":
    main()
