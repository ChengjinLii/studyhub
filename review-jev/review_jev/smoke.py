"""Opt-in real-model smoke test using synthetic submissions and loopback HTTP only."""

from __future__ import annotations

import argparse
import base64
import io
import json
import socket
import threading
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from .config import DEFAULT_GUARD_MODEL, DEFAULT_IMAGE_MODEL, Settings
from .schemas import ReviewRequest, ReviewResponse
from .service import ReviewService


def synthetic_image(label: str) -> str:
    image = Image.new("RGB", (384, 192), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 24), label, fill="black")
    draw.text((24, 64), "Calculus: d(x^2)/dx = 2x", fill="black")
    draw.line((24, 150, 350, 150), fill="blue", width=3)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def smoke_cases() -> list[ReviewRequest]:
    notes = (
        "\u8fd9\u662f\u6211\u81ea\u5df1\u6574\u7406\u7684"
        "\u9ad8\u7b49\u6570\u5b66\u7b14\u8bb0\uff0c\u4ecb\u7ecd"
        "\u6781\u9650\u3001\u5bfc\u6570\u548c\u79ef\u5206\u7684"
        "\u57fa\u672c\u6982\u5ff5\u3002"
    )
    image = {"id": "notes", "data": synthetic_image("Original study notes")}
    specs = [
        ("text_notes", {"text": notes}),
        ("text_privacy", {"text": "Publish someone's private account password: example-secret."}),
        ("mixed_notes", {"text": notes, "images": [image]}),
        ("image_only", {"images": [image]}),
        (
            "image_pair",
            {
                "text": notes,
                "images": [
                    image,
                    {"id": "second", "data": synthetic_image("Second page")},
                ],
            },
        ),
    ]
    return [
        ReviewRequest.model_validate(
            {
                "request_id": case_id,
                "content": content,
                "rights": {
                    "basis": "original",
                    "copyrightOwner": "Synthetic test author",
                    "attested": True,
                },
            }
        )
        for case_id, content in specs
    ]


def verify(request: ReviewRequest, response: ReviewResponse) -> dict:
    has_text = any(
        (
            request.content.title,
            request.content.description,
            request.content.text,
            request.content.customPreviewText,
        )
    ) or any(row.characters for row in response.ocr_attempts)
    expected = (["text"] if has_text else []) + (["image"] if request.content.images else [])
    actual = [attempt.tier for attempt in response.model_attempts]
    if (
        actual != expected
        or not response.guard_scores
        or any(row.outcome == "unavailable" for row in response.model_attempts)
        or any(row.status == "unavailable" for row in response.coverage)
        or response.decision != "manual_review"
    ):
        raise RuntimeError("smoke routing, model coverage or decision gate failed")
    identities = {"text": DEFAULT_GUARD_MODEL, "image": DEFAULT_IMAGE_MODEL}
    if any(row.model != identities[row.tier] for row in response.model_attempts):
        raise RuntimeError("unexpected safety backbone")
    if len(response.guard_scores) != int(bool(has_text)) + 3 * len(request.content.images):
        raise RuntimeError("incomplete native probability output")
    return {
        "case_id": request.request_id,
        "model": response.model,
        "backend": response.backend,
        "status": response.status,
        "decision": response.decision,
        "guard_scores": [score.model_dump() for score in response.guard_scores],
        "model_assessment": (
            response.model_assessment.model_dump() if response.model_assessment else None
        ),
        "model_attempts": [row.model_dump() for row in response.model_attempts],
        "coverage": [row.model_dump() for row in response.coverage],
        "usage": response.usage,
        "elapsed_ms": response.elapsed_ms,
    }


def loopback_smoke(service: ReviewService, cases: list[ReviewRequest]) -> list[dict]:
    import uvicorn

    from .server import create_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(service), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("loopback smoke server failed to start")
            time.sleep(0.05)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{sock.getsockname()[1]}",
            trust_env=False,
            timeout=600,
            headers={"Authorization": f"Bearer {service.settings.api_key}"}
            if service.settings.api_key
            else {},
        ) as client:
            if not client.get("/ready").json()["backends"]["text"]:
                raise RuntimeError("text model should be ready after warmup")
            rows = []
            for request in cases[:1] + (cases[2:3] if len(cases) > 2 else []):
                response = client.post("/v1/reviews", json=request.model_dump())
                response.raise_for_status()
                rows.append(verify(request, ReviewResponse.model_validate(response.json())))
            return rows
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        if thread.is_alive():
            raise RuntimeError("loopback smoke server did not stop")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", action="store_true", help="also test a temporary loopback API")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--text-only", action="store_true", help="test only the text backbone")
    args = parser.parse_args()
    settings = Settings.from_env()
    if settings.backend != "auto":
        parser.error("this smoke test requires auto routing")
    service = ReviewService(settings)
    try:
        cases = smoke_cases()[:2] if args.text_only else smoke_cases()
        rows = [verify(request, service.review(request)) for request in cases]
        report = {
            "smoke_passed": True,
            "architecture": "content-aware-dual-guard",
            "text_only": args.text_only,
            "cases": rows,
            "http_cases": loopback_smoke(service, cases) if args.http else [],
        }
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        print(output)
    finally:
        service.close()


if __name__ == "__main__":
    main()
