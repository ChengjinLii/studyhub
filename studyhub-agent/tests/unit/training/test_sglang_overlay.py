from __future__ import annotations

import json

import pytest

from scripts.train.prepare_sglang_model_overlay import prepare_overlay


def test_overlay_maps_composite_text_dimensions_and_links_weights(tmp_path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "model_type": "qwen3_5",
                "text_config": {
                    "vocab_size": 100,
                    "hidden_size": 64,
                    "num_hidden_layers": 2,
                    "intermediate_size": 192,
                    "num_attention_heads": 8,
                    "num_key_value_heads": 2,
                    "head_dim": 8,
                },
            }
        ),
        encoding="utf-8",
    )
    (model / "model.safetensors").write_bytes(b"weights")

    output = tmp_path / "overlay"
    manifest = prepare_overlay(model, output)
    config = json.loads((output / "config.json").read_text(encoding="utf-8"))

    assert config["vocab_size"] == 100
    assert config["hidden_size"] == 64
    assert config["num_hidden_layers"] == 2
    assert config["intermediate_size"] == 192
    assert config["num_attention_heads"] == 8
    assert config["num_key_value_heads"] == 2
    assert config["head_dim"] == 8
    assert config["text_config"]["num_experts"] == 1
    assert "num_experts" not in json.loads((model / "config.json").read_text())["text_config"]
    assert manifest["dense_lora_num_experts"] == 1
    assert (output / "model.safetensors").is_symlink()
    assert (output / "model.safetensors").resolve() == (model / "model.safetensors")
    assert manifest["mapped_text_config_fields"] == {
        "vocab_size": 100,
        "hidden_size": 64,
        "num_hidden_layers": 2,
        "intermediate_size": 192,
        "num_attention_heads": 8,
        "num_key_value_heads": 2,
        "head_dim": 8,
    }


@pytest.mark.parametrize(
    "text_config",
    [
        {"model_type": "qwen3_5_moe_text"},
        {"num_experts": 512},
        {"num_local_experts": 8},
    ],
)
def test_dense_overlay_rejects_moe_config(tmp_path, text_config) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text(json.dumps({"model_type": "qwen3_5", "text_config": text_config}))
    with pytest.raises(ValueError, match="MoE architecture"):
        prepare_overlay(model, tmp_path / "output")


def test_pinned_sglang_dense_config_does_not_inherit_expert_count() -> None:
    configs = pytest.importorskip("sglang.srt.configs.qwen3_5")
    config = configs.Qwen3_5Config(text_config={"num_experts": 1})
    assert config.get_text_config().num_experts == 1
