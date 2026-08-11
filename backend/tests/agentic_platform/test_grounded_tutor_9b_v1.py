from __future__ import annotations

import json
from pathlib import Path

from ml.agentic_platform.sft.build_grounded_tutor_9b_v1 import (
    EXPECTED_HOLDOUT_COUNT,
    EXPECTED_TRAINVAL_SPLITS,
    FAMILY_COUNTS,
    GROUNDED_TUTOR_SYSTEM_PROMPT,
    _has_excessive_repetition,
    build_grounded_tutor_9b_v1,
)
from ml.agentic_platform.sft.export_llamafactory import export_llamafactory_dataset
from ml.agentic_platform.sft.spec import load_jsonl


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _fixture_corpus(root: Path) -> tuple[Path, Path]:
    materials: list[dict[str, object]] = []
    transcriptions: list[dict[str, object]] = []
    for material_id in range(1, 31):
        materials.append(
            {
                "id": material_id,
                "title": f"课程 {material_id} 复习讲义",
                "description": "包含定义、推导、例题和复习提示。",
                "tags": ["课程复习", f"模块{material_id}"],
                "courseCategory": "专业课",
                "free": True,
                "price": 0,
            }
        )
        for page in (1, 2):
            transcriptions.append(
                {
                    "page_id": f"material_{material_id}_page_{page:04d}",
                    "material_id": material_id,
                    "title": f"课程 {material_id} 复习讲义",
                    "page": page,
                    "image_sha256": f"{material_id:04x}{page:04x}".ljust(64, "a"),
                    "parsed": {
                        "transcription": (
                            f"第{material_id}份讲义第{page}页先定义研究对象，随后列出"
                            "变量之间的关系和适用条件，并通过一个分步骤例题说明如何"
                            "检查计算过程。页面最后提醒读者区分已知条件、目标量与结论"
                            "边界，复习时需要逐项核对符号含义和推导前提。"
                        ),
                        "summary": (
                            f"第{page}页围绕定义、变量关系和适用条件展开，"
                            "并给出分步骤检查方法。"
                        ),
                        "readability": "high",
                        "contains_formula": True,
                    },
                }
            )

    materials.append(
        {
            "id": 999,
            "title": "不得进入训练的付费资料",
            "description": "付费内容",
            "tags": ["付费"],
            "free": False,
            "price": 10,
        }
    )
    transcriptions.append(
        {
            "page_id": "material_999_page_0001",
            "material_id": 999,
            "title": "不得进入训练的付费资料",
            "page": 1,
            "image_sha256": "f" * 64,
            "parsed": {
                "transcription": (
                    "本页首先界定研究对象与符号含义，然后从初始条件推导中间关系。"
                    "图表比较了三种输入条件下的变化趋势，例题则依次完成变量替换、"
                    "单位检查和边界验证。最后一段总结常见错误，提醒学习者不要把局部"
                    "结论扩展到未给出的情形，并建议通过反例检查公式的适用范围。"
                ),
                "summary": "这条页面摘要只用于验证付费资料会被构造器二次拒绝并记录。",
                "readability": "high",
                "contains_formula": False,
            },
        }
    )
    materials_path = root / "materials.jsonl"
    transcriptions_path = root / "transcriptions.jsonl"
    _write_jsonl(materials_path, materials)
    _write_jsonl(transcriptions_path, transcriptions)
    return materials_path, transcriptions_path


def test_repetition_filter_handles_chinese_runaway_text() -> None:
    repeated = "模型不得补全模糊内容，只能转录页面可见证据。" * 20
    normal = "".join(f"第{index}步检查不同变量及其适用边界。" for index in range(30))

    assert _has_excessive_repetition(repeated) is True
    assert _has_excessive_repetition(normal) is False


def test_builds_isolated_free_only_grounded_tutor_dataset(tmp_path: Path) -> None:
    materials_path, transcriptions_path = _fixture_corpus(tmp_path)
    output_dir = tmp_path / "training"
    holdout_dir = tmp_path / "sealed-holdout"

    manifest = build_grounded_tutor_9b_v1(
        materials_path=materials_path,
        transcriptions_path=transcriptions_path,
        output_dir=output_dir,
        holdout_dir=holdout_dir,
        generated_at="2026-08-11T00:00:00+00:00",
    )

    rows = load_jsonl(output_dir / "grounded_tutor_9b_v1_0_trainval.jsonl")
    holdout = load_jsonl(holdout_dir / "grounded_tutor_9b_holdout_120.jsonl")
    train_chunks = load_jsonl(output_dir / "clean_preview_chunks.jsonl")
    holdout_chunks = load_jsonl(holdout_dir / "sealed_preview_chunks.jsonl")
    train_material_ids = {
        int(ref["material_id"]) for row in rows for ref in row["evidence_refs"]
    }
    holdout_material_ids = {
        int(ref["material_id"])
        for row in holdout
        for ref in row["evidence_refs"]
    }

    assert manifest["records"] == sum(FAMILY_COUNTS.values()) - EXPECTED_HOLDOUT_COUNT
    assert manifest["split_counts"] == {
        key: value for key, value in EXPECTED_TRAINVAL_SPLITS.items() if value
    }
    assert manifest["excluded_nonfree_or_unknown_pages"] == 1
    assert len(holdout) == EXPECTED_HOLDOUT_COUNT
    assert all(row["training_eligible"] is False for row in holdout)
    assert all(
        row["messages"][0]["content"] == GROUNDED_TUTOR_SYSTEM_PROMPT
        for row in rows + holdout
    )
    assert all(
        '"chunk_id"' in row["messages"][0]["content"]
        and '"mode":"final"' in row["messages"][0]["content"]
        and "禁止输出 actions" in row["messages"][0]["content"]
        for row in rows + holdout
    )
    for row in rows + holdout:
        payload = json.loads(row["messages"][1]["content"])
        observation = payload["tool_observations"][0]
        if observation["tool"] == "read_pdf_evidence":
            assert "pages" not in observation["result"]
            assert all(
                item["chunk_id"] == item["evidence_id"]
                for item in observation["result"]["evidence"]
            )
        else:
            assert all(
                item.get("chunk_id")
                for item in observation["result"]["materials"]
            )
    assert train_material_ids.isdisjoint(holdout_material_ids)
    assert 999 not in train_material_ids | holdout_material_ids
    assert {
        int(chunk["material_id"]) for chunk in train_chunks
    }.isdisjoint({int(chunk["material_id"]) for chunk in holdout_chunks})
    assert manifest["holdout"]["evaluated"] is False
    assert "material_ids" not in manifest["holdout"]
    assert len(manifest["system_prompt_sha256"]) == 64

    export = export_llamafactory_dataset(
        source_path=output_dir / "grounded_tutor_9b_v1_0_trainval.jsonl",
        dataset_dir=output_dir / "llamafactory",
        materials_path=materials_path,
        chunks_path=output_dir / "clean_preview_chunks.jsonl",
        expected_profile_count=1080,
        expected_split_counts=EXPECTED_TRAINVAL_SPLITS,
        target_profile="grounded_tutor_9b",
        file_prefix="grounded_tutor_9b",
        dataset_name_prefix="studyhub_grounded_tutor_9b",
    )
    assert export["counts"] == EXPECTED_TRAINVAL_SPLITS
    assert export["assistant_only_loss"] is True
    assert export["target_profile"] == "grounded_tutor_9b"
