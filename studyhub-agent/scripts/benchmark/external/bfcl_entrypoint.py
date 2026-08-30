#!/usr/bin/env python3
"""Run the pinned BFCL CLI with the StudyHub checkpoint registered as Qwen FC."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig  # noqa: E402
from bfcl_eval.model_handler.local_inference.qwen_fc import QwenFCHandler  # noqa: E402
from overrides import override  # noqa: E402

from external_benchmarks.adapters.bfcl_prompt import disable_thinking_generation_prefix  # noqa: E402

REGISTRY_NAME = os.environ.get(
    "STUDYHUB_BFCL_REGISTRY_NAME",
    "StudyHub/Qwen3.5-9B-Open-Agentic-v2-FC",
)
DISPLAY_NAME = os.environ.get(
    "STUDYHUB_BFCL_DISPLAY_NAME",
    "StudyHub Qwen3.5-9B Open-Agentic v2 (FC)",
)


class StudyHubQwenFCHandler(QwenFCHandler):
    @override
    def _format_prompt(self, messages, function):
        return disable_thinking_generation_prefix(super()._format_prompt(messages, function))


def register_studyhub_model() -> None:
    model_path = Path(os.environ["STUDYHUB_BFCL_MODEL_PATH"]).resolve()
    if not (model_path / "config.json").is_file():
        raise RuntimeError(f"invalid StudyHub model artifact: {model_path}")
    MODEL_CONFIG_MAPPING[REGISTRY_NAME] = ModelConfig(
        model_name=str(model_path),
        display_name=DISPLAY_NAME,
        url="https://github.com/ChengjinLii/studyhub",
        org="StudyHub",
        license="apache-2.0",
        model_handler=StudyHubQwenFCHandler,
        input_price=None,
        output_price=None,
        is_fc_model=True,
        underscore_to_dot=False,
    )


def main() -> None:
    register_studyhub_model()
    # Import after registration so both generation and evaluation see the entry.
    from bfcl_eval.__main__ import cli

    cli()


if __name__ == "__main__":
    main()
