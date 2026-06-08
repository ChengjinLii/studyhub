from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.schemas.ai import AiRecommendRequestPayload


def _data_url(mime_type: str, body: bytes) -> str:
    encoded = base64.b64encode(body).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def test_ai_recommendation_accepts_single_valid_image_attachment() -> None:
    payload = AiRecommendRequestPayload(
        query="帮我分析这道题",
        imageAttachments=[
            {
                "name": "question.png",
                "mimeType": "IMAGE/PNG",
                "dataUrl": _data_url("image/png", b"image"),
                "sizeBytes": 5,
            },
            {
                "name": "ignored.webp",
                "mimeType": "image/webp",
                "dataUrl": _data_url("image/webp", b"ignored"),
                "sizeBytes": 7,
            },
        ],
    )

    assert len(payload.imageAttachments) == 1
    assert payload.imageAttachments[0].mimeType == "image/png"
    assert payload.imageAttachments[0].name == "question.png"


def test_ai_recommendation_rejects_image_mime_data_url_mismatch() -> None:
    with pytest.raises(ValidationError, match="图片 MIME 与 data URL 不一致"):
        AiRecommendRequestPayload(
            query="帮我分析这道题",
            imageAttachments=[
                {
                    "name": "question.png",
                    "mimeType": "image/png",
                    "dataUrl": _data_url("image/jpeg", b"image"),
                    "sizeBytes": 5,
                }
            ],
        )


def test_ai_recommendation_rejects_invalid_base64_image_data_url() -> None:
    with pytest.raises(ValidationError, match="有效 base64"):
        AiRecommendRequestPayload(
            query="帮我分析这道题",
            imageAttachments=[
                {
                    "name": "question.png",
                    "mimeType": "image/png",
                    "dataUrl": "data:image/png;base64,not-valid-base64",
                    "sizeBytes": 5,
                }
            ],
        )


def test_ai_recommendation_rejects_decoded_image_over_limit() -> None:
    oversized = b"x" * 786_433

    with pytest.raises(ValidationError, match="图片不能超过 768KB"):
        AiRecommendRequestPayload(
            query="帮我分析这道题",
            imageAttachments=[
                {
                    "name": "question.png",
                    "mimeType": "image/png",
                    "dataUrl": _data_url("image/png", oversized),
                    "sizeBytes": 1,
                }
            ],
        )
