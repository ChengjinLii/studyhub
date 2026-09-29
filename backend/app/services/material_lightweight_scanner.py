from __future__ import annotations

import os
from pathlib import Path
import resource
import sys

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_ACTIVE_CONTENT_KEYS = {
    "/AA",
    "/EmbeddedFile",
    "/EmbeddedFiles",
    "/ImportData",
    "/JavaScript",
    "/JS",
    "/Launch",
    "/OpenAction",
    "/RichMedia",
    "/SubmitForm",
    "/XFA",
}
PDF_OBJECT_INSPECTION_LIMIT = 20_000
IMAGE_PIXEL_LIMIT = 100_000_000


def _apply_resource_limits() -> None:
    memory_bytes = int(os.environ.get("STUDYHUB_SCANNER_MEMORY_MB", "384")) * 1024 * 1024
    cpu_seconds = int(os.environ.get("STUDYHUB_SCANNER_CPU_SECONDS", "20"))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _pdf_contains_active_content(reader: PdfReader) -> bool:
    stack: list[object] = [reader.trailer]
    seen_indirect: set[tuple[int, int]] = set()
    seen_containers: set[int] = set()
    inspected = 0
    while stack:
        current = stack.pop()
        if isinstance(current, IndirectObject):
            reference = (int(current.idnum), int(current.generation))
            if reference in seen_indirect:
                continue
            seen_indirect.add(reference)
            current = current.get_object()
        if isinstance(current, (DictionaryObject, ArrayObject)):
            container_id = id(current)
            if container_id in seen_containers:
                continue
            seen_containers.add(container_id)
        inspected += 1
        if inspected > PDF_OBJECT_INSPECTION_LIMIT:
            return True
        if isinstance(current, DictionaryObject):
            if PDF_ACTIVE_CONTENT_KEYS.intersection(str(key) for key in current.keys()):
                return True
            stack.extend(current.values())
        elif isinstance(current, ArrayObject):
            stack.extend(current)
    return False


def _scan_pdf(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            if handle.read(8).lstrip()[:5] != b"%PDF-":
                return "ESCALATE"
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted or len(reader.pages) < 1 or _pdf_contains_active_content(reader):
            return "ESCALATE"
    except Exception:  # noqa: BLE001
        return "ESCALATE"
    return "CLEAN"


def _scan_image(path: Path) -> str:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > IMAGE_PIXEL_LIMIT:
                return "ESCALATE"
            if (image.format or "").upper() not in {"PNG", "JPEG", "WEBP", "GIF", "BMP"}:
                return "ESCALATE"
            image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return "ESCALATE"
    return "CLEAN"


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    _apply_resource_limits()
    path = Path(sys.argv[1])
    suffix = path.suffix.lower()
    decision = _scan_pdf(path) if suffix == ".pdf" else _scan_image(path) if suffix in IMAGE_SUFFIXES else "ESCALATE"
    sys.stdout.write(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
