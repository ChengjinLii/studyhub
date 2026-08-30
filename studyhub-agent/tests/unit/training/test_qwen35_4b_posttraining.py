import hashlib
import json
from pathlib import Path

import yaml

from scripts.models.lock_qwen35_model import aggregate_weight_set, build_lock
from scripts.models.prepare_qwen35_tokenizer_overlay import prepare_overlay
from scripts.train.audit_qwen35_4b_9b_tokenizer_parity import select_rows

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _json(relative: str) -> dict:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


def test_model_lock_hashes_complete_snapshot(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    files = {
        "config.json": json.dumps({"model_type": "qwen3_5"}),
        "model.safetensors.index.json": json.dumps({"weight_map": {"x": "model-1.safetensors"}}),
        "model-1.safetensors": "weights",
        "LICENSE": "Apache License",
        "tokenizer.json": "{}",
        "tokenizer_config.json": "{}",
        "chat_template.jinja": "template",
        "vocab.json": "{}",
        "merges.txt": "",
    }
    for name, content in files.items():
        (model / name).write_text(content, encoding="utf-8")

    lock = build_lock(model, "Qwen/Test", "abc123", "Apache-2.0")

    assert lock["status"] == "LOCKED"
    assert lock["resolved_revision"] == "abc123"
    assert lock["aggregate_weight_set_sha256"] == aggregate_weight_set(lock["weight_shards"])
    assert lock["tokenizer_files"]["tokenizer.json"]["sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert lock["chat_template"]["source"] == "chat_template.jinja"


def test_canonical_tokenizer_overlay_keeps_student_weights(tmp_path: Path) -> None:
    student = tmp_path / "student"
    teacher = tmp_path / "teacher"
    output = tmp_path / "overlay"
    student.mkdir()
    teacher.mkdir()
    (student / "config.json").write_text("{}", encoding="utf-8")
    (student / "weights.safetensors").write_bytes(b"student")
    (student / "studyhub_download_manifest.json").write_text(
        json.dumps(
            {
                "repository": "Qwen/Test-Base",
                "revision": "fixed",
                "weight_shards": [{"name": "weights.safetensors", "bytes": 7}],
            }
        ),
        encoding="utf-8",
    )
    for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "vocab.json", "merges.txt"):
        (teacher / name).write_text(f"teacher:{name}", encoding="utf-8")

    manifest = prepare_overlay(student, teacher, output)

    assert manifest["status"] == "LOCKED"
    assert (output / "weights.safetensors").resolve() == (student / "weights.safetensors").resolve()
    assert (output / "tokenizer.json").resolve() == (teacher / "tokenizer.json").resolve()


def test_parity_sample_selection_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "rows.jsonl"
    source.write_text("".join(json.dumps({"id": f"row-{i}"}) + "\n" for i in range(20)), encoding="utf-8")

    first = [row["id"] for row in select_rows(source, 10)]
    second = [row["id"] for row in select_rows(source, 10)]

    assert first == second
    assert len(set(first)) == 10


def test_program_roles_and_sft1_recipe_are_frozen() -> None:
    program = _json("configs/program-v4/qwen35-4b-agent-posttraining.json")
    config = yaml.safe_load((PROJECT_ROOT / "configs/train/qwen35-4b-open-agentic-sft1.yaml").read_text())
    thinking = _json("docs/training/evidence/qwen35-4b-9b-thinking-contract.json")

    assert program["roles"]["M0"]["model"] == "Qwen/Qwen3.5-4B-Base"
    assert program["roles"]["T9"]["model"] == "Qwen/Qwen3.5-9B"
    assert program["contracts"]["main_grpo_allowed"] is False
    assert config["actor"]["lora_rank"] == config["actor"]["lora_alpha"] == 32
    assert config["actor"]["target_modules"] == ["o_proj", "gate_proj", "up_proj", "down_proj"]
    assert config["actor"]["path"].endswith("qwen35-4b-base-canonical-tokenizer")
    assert config["train_dataset"]["path"].endswith("open_agentic_sft_v2_qwen35_9b/hf_dataset")
    assert thinking["enable_thinking"] is False
    assert thinking["chain_of_thought_collected"] is False


def test_fresh_external_holdouts_are_locked_and_not_training_data() -> None:
    bfcl = _json("configs/eval/bfcl-4b-pipeline-holdout-v1.json")
    tau2 = _json("configs/eval/tau2-4b-pipeline-holdout-v1.json")

    assert bfcl["status"] == tau2["status"] == "LOCKED_UNEXPOSED"
    assert bfcl["training_access"] is tau2["training_access"] is False
    assert bfcl["opened_for_model_selection"] is tau2["opened_for_model_selection"] is False
    assert all(len(ids) == 10 for ids in bfcl["task_ids"].values())
    assert all(len(ids) == 5 for ids in tau2["task_ids"].values())
    assert sum(map(len, bfcl["task_ids"].values())) == 70
    assert sum(map(len, tau2["task_ids"].values())) == 15


def test_download_script_pins_4b_base_and_proxy() -> None:
    launcher = (PROJECT_ROOT / "scripts/models/download_qwen35_controlled.sh").read_text()

    assert "Qwen/Qwen3.5-4B-Base" in launcher
    assert "1001bb4d826a52d1f399e183466143f4da7b741b" in launcher
    assert "http://127.0.0.1:7892" in launcher
