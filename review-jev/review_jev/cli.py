from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import Settings
from .media import InvalidImage
from .policy import load_policy
from .schemas import ReviewRequest
from .service import ReviewService


def main() -> None:
    parser = argparse.ArgumentParser(prog="review-jev", description="Standalone StudyHub review")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the review API; no database needed")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8011)
    review = commands.add_parser("review", help="review a JSON file, or - for stdin")
    review.add_argument("request")
    evaluate = commands.add_parser("evaluate", help="evaluate labeled JSONL; no training")
    evaluate.add_argument("dataset")
    evaluate.add_argument("--output", type=Path)
    policy = commands.add_parser("policy", help="print the versioned review policy")
    for command in (serve, review, policy, evaluate):
        command.add_argument(
            "--backend", choices=["auto", "qwen3guard", "onejev-http", "torch", "demo"]
        )
        command.add_argument("--image-backend", choices=["torch", "onejev-http"])
        command.add_argument("--onejev-url")
        command.add_argument("--model")
        command.add_argument("--model-revision")
        command.add_argument("--text-model")
        command.add_argument("--text-model-revision")
        command.add_argument("--cascade-enabled", action=argparse.BooleanOptionalAction)
        command.add_argument("--text-confidence-threshold", type=float)
        command.add_argument("--image-confidence-threshold", type=float)
        command.add_argument("--large-confidence-threshold", type=float)
        command.add_argument("--large-backend", choices=["torch", "onejev-http"])
        command.add_argument("--large-model")
        command.add_argument("--large-model-revision")
        command.add_argument("--large-onejev-url")
        command.add_argument("--large-served-model")
        command.add_argument("--large-device")
        command.add_argument("--device")
        command.add_argument("--text-device")
        command.add_argument("--served-model")
        command.add_argument("--policy", dest="policy_path")
    args = parser.parse_args()
    try:
        env_settings = Settings.from_env()
        values = env_settings.model_dump()
        if args.backend and args.backend != env_settings.backend:
            if args.model is None and not os.environ.get("REVIEW_JEV_MODEL"):
                values.pop("model")
        if args.backend or args.model:
            if args.model_revision is None and not os.environ.get("REVIEW_JEV_MODEL_REVISION"):
                values.pop("model_revision", None)
        if (
            args.text_model
            and args.text_model_revision is None
            and not os.environ.get("REVIEW_JEV_TEXT_MODEL_REVISION")
        ):
            values.pop("text_model_revision", None)
        if (
            args.large_model
            and args.large_model_revision is None
            and not os.environ.get("REVIEW_JEV_LARGE_MODEL_REVISION")
        ):
            values.pop("large_model_revision", None)
        settings = Settings.model_validate(
            {
                **values,
                **{
                    key: getattr(args, key)
                    for key in (
                        "backend",
                        "image_backend",
                        "onejev_url",
                        "model",
                        "model_revision",
                        "text_model",
                        "text_model_revision",
                        "cascade_enabled",
                        "text_confidence_threshold",
                        "image_confidence_threshold",
                        "large_confidence_threshold",
                        "large_backend",
                        "large_model",
                        "large_model_revision",
                        "large_onejev_url",
                        "large_served_model",
                        "large_device",
                        "device",
                        "text_device",
                        "served_model",
                        "policy_path",
                    )
                    if getattr(args, key) is not None
                },
            }
        )
        if args.command == "policy":
            print(load_policy(settings.policy_path).model_dump_json(indent=2))
            return
        service = ReviewService(settings)
        if args.command == "serve":
            import uvicorn

            from .server import create_app

            if args.host not in {"127.0.0.1", "localhost", "::1"} and not settings.api_key:
                parser.error("set REVIEW_JEV_API_KEY before binding a non-loopback interface")
            uvicorn.run(create_app(service), host=args.host, port=args.port, log_level="info")
            return
        try:
            if args.command == "evaluate":
                from .evaluate import evaluate_file

                report = evaluate_file(service, Path(args.dataset))
                output = json.dumps(report, ensure_ascii=False, indent=2)
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(output + "\n", encoding="utf-8")
                print(output)
                return
            raw = sys.stdin.read() if args.request == "-" else Path(args.request).read_text("utf-8")
            request = ReviewRequest.model_validate_json(raw)
            print(service.review(request).model_dump_json(indent=2))
        finally:
            service.close()
    except ValidationError:
        print("Invalid request or settings; consult the schema at /docs.", file=sys.stderr)
        raise SystemExit(2) from None
    except (InvalidImage, OSError, ValueError) as exc:
        print(f"Review failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
