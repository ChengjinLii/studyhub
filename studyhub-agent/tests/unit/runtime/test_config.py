from pathlib import Path

from studyhub_agent.runtime.config import load_phase1_config

ROOT = Path(__file__).resolve().parents[3]


def test_phase1_configuration_loads_and_serializes() -> None:
    config = load_phase1_config(
        ROOT / "configs/agent/studyhub-v2.yaml",
        ROOT / "configs/env/train.yaml",
    )

    assert config.profile.prompt_version == "studyhub-v2"
    assert config.profile.tool_schema_version == "v1"
    assert config.environment.name == "train"
    assert config.environment.fixture_mode is True
    assert config.environment.allow_network is False
    assert config.to_dict()["profile"]["max_tool_calls"] == 8
