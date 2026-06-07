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
