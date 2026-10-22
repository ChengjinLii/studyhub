import json
import sys
from pathlib import Path

import pytest

from studyhub_agent.contracts.render import TEMPLATE_PATH
from studyhub_agent.serving.config import ServingConfig


@pytest.fixture
def serving_config(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "model_type": "qwen3_5",
                "architectures": ["Qwen3_5ForConditionalGeneration"],
                "text_config": {"max_position_embeddings": 262144},
            }
        )
    )
    (model / "tokenizer.json").write_text("{}")
    (model / "tokenizer_config.json").write_text("{}")
    (model / "chat_template.jinja").write_bytes(TEMPLATE_PATH.read_bytes())
    (model / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"test": "model.safetensors"}}))
    (model / "model.safetensors").write_bytes(b"fixture-not-a-real-model")
    return ServingConfig(model_dir=model, runtime_python=Path(sys.executable), state_dir=tmp_path / "state")


@pytest.fixture
def gpu():
    return {
        "index": "0",
        "uuid": "GPU-12345678-1234-1234-1234-123456789abc",
        "name": "H100",
        "driver": "580.99",
        "total_mib": 80000,
        "free_mib": 80000,
        "utilization": 0,
        "pids": [],
    }
