from __future__ import annotations

import hashlib
import io
import subprocess
import threading
from pathlib import Path
from typing import Protocol

from studyhub_agent.contracts.knowledge import Document, PageSpan
from studyhub_agent.knowledge.chunking import make_document

_PDFIUM_LOCK = threading.Lock()


class DocumentParseError(ValueError):
    pass


class ImageOCR(Protocol):
    identity: str

    def read(self, image: bytes) -> str: ...


class TesseractOCR:
    def __init__(self, languages: str = "chi_sim+eng", timeout: float = 30):
        self.languages, self.timeout = languages, timeout
        self.identity = f"tesseract:{languages}:v1"

    def read(self, image: bytes) -> str:
        try:
            result = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", self.languages],
                input=image,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout,
                check=True,
            )
            if len(result.stdout) > 2_000_000:
                raise DocumentParseError("OCR output exceeds the document limit")
            return result.stdout.decode("utf-8").strip()
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise DocumentParseError("OCR unavailable, timed out or returned invalid text") from exc


def scanned_page(image_area_ratio: float, text_length: int) -> bool:
    # WeKnora's per-page routing: do not trust a hidden OCR layer on an image-dominated page.
    return image_area_ratio >= 0.5 or (text_length < 10 and image_area_ratio >= 0.1)


def parse_pdf(path: Path, kb: str, ocr: ImageOCR, *, max_pages: int = 200) -> Document:
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
    except ImportError as exc:
        raise DocumentParseError("PDF parsing requires the documents optional dependencies") from exc
    parts, spans, cursor = [], [], 0
    source_bytes = path.read_bytes()
    try:
        # PDFium has process-global state and must not run concurrently in worker threads.
        with _PDFIUM_LOCK, pdfium.PdfDocument(source_bytes) as pdf:
            if not 0 < len(pdf) <= max_pages:
                raise DocumentParseError("PDF page limit exceeded or empty PDF")
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    width, height = page.get_size()
                    if not 0 < width * height <= 12_000_000:
                        raise DocumentParseError("PDF page geometry exceeds limits")
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()
                    finally:
                        textpage.close()
                    area = 0.0
                    for obj in page.get_objects():
                        if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                            left, bottom, right, top = obj.get_bounds()
                            area += abs((right - left) * (top - bottom))
                    method = "native"
                    if scanned_page(area / (width * height), len(text.strip())):
                        scale = min(2.0, (12_000_000 / (width * height)) ** 0.5)
                        bitmap = page.render(scale=scale)
                        try:
                            image = bitmap.to_pil()
                            output = io.BytesIO()
                            image.save(output, format="PNG")
                            text = ocr.read(output.getvalue())
                            image.close()
                        finally:
                            bitmap.close()
                        if not text.strip():
                            raise DocumentParseError("scanned PDF page has no usable OCR text")
                        method = "ocr"
                    body = text + ("\n\n" if index + 1 < len(pdf) else "")
                    spans.append(PageSpan(page=index + 1, start=cursor, end=cursor + len(body), method=method))
                    parts.append(body)
                    cursor += len(body)
                    if cursor > 2_000_000:
                        raise DocumentParseError("parsed PDF exceeds the document character limit")
                finally:
                    page.close()
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("PDF cannot be parsed safely") from exc
    text = "".join(parts)
    if not text.strip():
        raise DocumentParseError("PDF has no usable content")
    return make_document(
        kb,
        str(path.resolve()),
        text,
        title=path.stem,
        pages=tuple(spans),
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        parser=f"pdfium-page-routing-v1:{ocr.identity}",
    )


def parse_document(path: Path, kb: str, *, ocr: ImageOCR | None = None) -> Document:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_000_000:
        raise DocumentParseError("source must be an explicit local file up to 32 MB")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path, kb, ocr or TesseractOCR())
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        from PIL import Image, ImageOps

        try:
            source_bytes = path.read_bytes()
            with Image.open(io.BytesIO(source_bytes)) as original:
                if (
                    original.format not in {"PNG", "JPEG", "WEBP"}
                    or original.width * original.height > 12_000_000
                    or getattr(original, "n_frames", 1) != 1
                ):
                    raise DocumentParseError("image geometry or frame count exceeds limits")
                visible = ImageOps.exif_transpose(original).convert("RGBA")
                image = Image.new("RGB", visible.size, "white")
                image.paste(visible, mask=visible.getchannel("A"))
                visible.close()
                output = io.BytesIO()
                image.save(output, format="PNG")
                image.close()
            engine = ocr or TesseractOCR()
            text = engine.read(output.getvalue())
            if not text.strip():
                raise DocumentParseError("image has no usable OCR text")
            return make_document(
                kb,
                str(path.resolve()),
                text,
                title=path.stem,
                pages=(PageSpan(page=1, start=0, end=len(text), method="ocr"),),
                source_sha256=hashlib.sha256(source_bytes).hexdigest(),
                parser=engine.identity,
            )
        except (OSError, ValueError) as exc:
            raise DocumentParseError("image cannot be decoded or recognized") from exc
    if suffix not in {".md", ".txt"} or path.stat().st_size > 4_000_000:
        raise DocumentParseError("supported sources: Markdown, TXT, PDF and raster images")
    with path.open(encoding="utf-8", newline="") as handle:
        return make_document(kb, str(path.resolve()), handle.read(), title=path.stem)
