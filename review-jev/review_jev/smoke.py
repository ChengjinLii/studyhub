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

from .config import DEFAULT_GUARD_MODEL, DEFAULT_ONEJEV_MODEL, Settings
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
    has_images = bool(request.content.images)
    expected_model = DEFAULT_ONEJEV_MODEL if has_images else DEFAULT_GUARD_MODEL
    if response.model != expected_model or response.decision != "manual_review":
        raise RuntimeError("smoke routing or decision gate failed")
    if has_images:
        if response.status != "completed" or response.backend != "torch":
            raise RuntimeError("multimodal model smoke failed")
        checks = [item for item in response.findings if item.source == "model"]
        if len(checks) != 11 or any(item.risk_probability is None for item in checks):
            raise RuntimeError("multimodal model did not return all rule probabilities")
    elif response.status != "partial" or response.model_assessment is None:
        raise RuntimeError("text guard smoke failed")
    return {
        "case_id": request.request_id,
        "model": response.model,
        "model_revision": response.model_revision,
        "backend": response.backend,
        "status": response.status,
        "decision": response.decision,
        "model_assessment": (
            response.model_assessment.model_dump() if response.model_assessment else None
        ),
        "model_checks": sum(item.source == "model" for item in response.findings),
        "risk_signals": [
            item.rule_id for item in response.findings if item.outcome in {"review", "reject"}
        ],
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
            if client.get("/ready").status_code != 200:
                raise RuntimeError("both routed models should be ready after warmup")
            rows = []
            for request in (cases[0], cases[2]):
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
    args = parser.parse_args()
    settings = Settings.from_env()
    if settings.backend != "auto" or settings.image_backend != "torch":
        parser.error("this smoke test requires auto routing with local torch images")
    service = ReviewService(settings)
    try:
        cases = smoke_cases()
        rows = []
        for request in cases:
            row = verify(request, service.review(request))
            rows.append(row)
            print(f"smoke passed: {request.request_id} ({row['backend']})", flush=True)
        image_device = str(service.backend.images.engine.device)
        report = {
            "smoke_passed": True,
            "business_connected": False,
            "database_connected": False,
            "image_device": image_device,
            "cases": rows,
            "http_cases": loopback_smoke(service, cases) if args.http else [],
            "limitations": [
                "Synthetic smoke cases verify inference and routing, not moderation accuracy.",
                "No production services, databases, or user submissions were accessed.",
            ],
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
