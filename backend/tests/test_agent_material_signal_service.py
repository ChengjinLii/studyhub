from __future__ import annotations

import json

from app.models.materials import MaterialRecord
from app.services.agent_material_signal_service import build_material_signals


def test_agent_material_signals_capture_quality_and_risk_without_extra_io() -> None:
    material = MaterialRecord(
        id=901,
        title="通信原理四年真题解析",
        description="2021-2024 通信原理期末真题、答案解析和常考题型整理",
        tags_json=json.dumps(["通信原理", "真题", "解析"], ensure_ascii=False),
        file_storage_key="materials/cps.pdf",
        file_type="pdf",
        preview_status="done",
        review_status="APPROVED",
        copyright_owner="课程组",
        is_free=False,
        price=300,
        download_count=80,
        like_count=15,
        rating_avg=4.7,
        rating_count=5,
    )

    signals = build_material_signals(material)
    payload = signals.to_prompt_payload()

    assert payload["quality_score"] >= 12
    assert "简介完整" in payload["quality_signals"]
    assert "审核通过" in payload["quality_signals"]
    assert "版权归属已标注" in payload["quality_signals"]
    assert "高评分资料" in payload["quality_signals"]
    assert "risk_signals" not in payload


def test_agent_material_signals_flag_bounded_review_and_copyright_risks() -> None:
    material = MaterialRecord(
        id=902,
        title="通信原理资料",
        description="短简介",
        tags_json=json.dumps(["通信原理"], ensure_ascii=False),
        file_type="pdf",
        preview_status="processing",
        review_status="NEEDS_CHANGES",
        is_free=False,
        price=500,
        rating_avg=2.5,
        rating_count=2,
    )

    signals = build_material_signals(material)

    assert "简介较短" in signals.risk_signals
    assert "交付信息缺失" in signals.risk_signals
    assert "预览未就绪" in signals.risk_signals
    assert "审核状态需复核" in signals.risk_signals
    assert "版权归属未标注" in signals.risk_signals
    assert "评分偏低" in signals.risk_signals


def test_agent_material_signals_flag_content_moderation_risks_without_extra_io() -> None:
    material = MaterialRecord(
        id=903,
        title="通信原理资料包",
        description="资料含内部泄题和保过服务，加微信 studyhub_user 领取。",
        tags_json=json.dumps(["通信原理", "资料"], ensure_ascii=False),
        file_storage_key="materials/risky.pdf",
        file_type="pdf",
        preview_status="done",
        review_status="APPROVED",
        is_free=True,
        download_count=2,
    )

    signals = build_material_signals(material)

    assert "外部联系方式需复核" in signals.risk_signals
    assert "疑似违规交易风险" in signals.risk_signals
    assert "疑似版权或来源风险" in signals.risk_signals


def test_agent_material_signals_tolerate_unloaded_compatibility_columns() -> None:
    material = MaterialRecord(
        id=904,
        title="ESD-电子系统设计-2021年真题及答案",
        description="电子系统设计 2021 年真题、样卷答案和期末考题风格整理",
        file_type="pdf",
        is_free=True,
        download_count=12,
        rating_avg=4.5,
        rating_count=3,
    )
    for field in ("tags_json", "file_storage_key", "preview_status", "copyright_owner"):
        material.__dict__.pop(field, None)

    signals = build_material_signals(material)

    assert signals.quality_score >= 1
    assert "简介完整" in signals.quality_signals
