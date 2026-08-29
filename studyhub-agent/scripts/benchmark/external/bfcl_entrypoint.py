#!/usr/bin/env python3
"""Run the pinned BFCL CLI with the StudyHub checkpoint registered as Qwen FC."""

from __future__ import annotations

import os
from pathlib import Path

from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig
from bfcl_eval.model_handler.local_inference.qwen_fc import QwenFCHandler

REGISTRY_NAME = os.environ.get(
    "STUDYHUB_BFCL_REGISTRY_NAME",
    "StudyHub/Qwen3.5-9B-Open-Agentic-v2-FC",
)
DISPLAY_NAME = os.environ.get(
    "STUDYHUB_BFCL_DISPLAY_NAME",
    "StudyHub Qwen3.5-9B Open-Agentic v2 (FC)",
)


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
        model_handler=QwenFCHandler,
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
