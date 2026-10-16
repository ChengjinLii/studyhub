from __future__ import annotations

import base64
import csv
import io
import math
import subprocess
from dataclasses import dataclass

from .config import Settings
from .schemas import OCRAttempt


@dataclass(frozen=True)
class OCRResult:
    attempt: OCRAttempt
    text: str = ""


def parse_tsv(image_id: str, output: str, settings: Settings) -> OCRResult:
    reader = csv.DictReader(io.StringIO(output), delimiter="\t")
    required = {"level", "conf", "text", "page_num", "block_num", "par_num", "line_num"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("invalid OCR response")
    lines: dict[tuple[str, ...], list[str]] = {}
    confidences, characters = [], 0
    for row in reader:
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        confidence = float(row["conf"]) / 100
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("invalid OCR confidence")
        characters += len(text) + 1
        if characters > settings.max_ocr_characters:
            raise ValueError("OCR character limit exceeded")
        key = tuple(row[key] for key in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(text)
        confidences.append(confidence)
    text = "\n".join(" ".join(words) for words in lines.values())
    confidence = min(confidences) if confidences else None
    status = (
        "empty"
        if not text
        else ("low_confidence" if confidence < settings.ocr_min_confidence else "completed")
    )
    return OCRResult(
        OCRAttempt(image_id=image_id, status=status, characters=len(text), confidence=confidence),
        text,
    )


class TesseractOCR:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, image_id: str, uri: str) -> OCRResult:
        if self.settings.ocr_backend == "disabled":
            return OCRResult(OCRAttempt(image_id=image_id, status="disabled"))
        try:
            raw = base64.b64decode(uri.split(",", 1)[1], validate=True)
            response = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", self.settings.ocr_languages, "tsv"],
                input=raw,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self.settings.ocr_timeout_seconds,
                check=True,
            )
            if len(response.stdout) > 4 * 1024 * 1024:
                raise ValueError("OCR response limit exceeded")
            return parse_tsv(image_id, response.stdout.decode("utf-8"), self.settings)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, KeyError):
            return OCRResult(OCRAttempt(image_id=image_id, status="unavailable"))
