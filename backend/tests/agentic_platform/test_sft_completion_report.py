from __future__ import annotations

from ml.agentic_platform.sft.build_completion_report import (
    _knowledge_cards,
    _line_chart,
)


def test_completion_report_contains_all_seventeen_knowledge_cards() -> None:
    rendered = _knowledge_cards(
        router_gate={"passed": False},
        router_token_limit=1800,
        tutor_holdout_rate=119 / 120,
    )

    assert rendered.count('class="knowledge-card"') == 17
    assert 'id="k01"' in rendered
    assert 'id="k17"' in rendered
    assert "教师审校 Silver" in rendered


def test_loss_chart_renders_training_and_validation_series() -> None:
    rendered = _line_chart(
        chart_id="test-loss",
        train_points=[(1, 1.0), (2, 0.5)],
        eval_points=[(1, 0.8), (2, 0.4)],
        y_label="loss",
    )

    assert 'id="test-loss"' in rendered
    assert rendered.count("<polyline") == 2
    assert "train-line" in rendered
    assert "eval-line" in rendered
