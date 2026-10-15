"""Credential-free child process. No network, PDF JavaScript or form execution."""
from __future__ import annotations

import json
import math
from pathlib import Path
import resource
import sys


def _deny_network() -> None:
    if sys.platform != "linux":
        return
    import ctypes
    import errno

    seccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("cannot initialize renderer isolation")
    try:
        for name in (b"socket", b"connect", b"socketpair"):
            number = seccomp.seccomp_syscall_resolve_name(name)
            if number >= 0 and seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError("cannot install renderer network rule")
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("cannot isolate renderer network")
    finally:
        seccomp.seccomp_release(context)


def watermark_image(image, enabled: bool):
    from PIL import Image, ImageDraw, ImageFont

    image = image.convert("RGB")
    if not enabled:
        return image
    width, height = image.size
    size = max(14, min(48, width // 22))
    font = ImageFont.load_default(size=size)
    tile = Image.new("RGBA", (size * 9, size * 4))
    ImageDraw.Draw(tile).text((size // 2, size), "StudyHub", font=font, fill=(80, 88, 100, 48))
    tile = tile.rotate(24, resample=Image.Resampling.BICUBIC, expand=True)
    overlay = Image.new("RGBA", image.size)
    for y in range(-tile.height, height, tile.height):
        for x in range(-tile.width, width, tile.width):
            overlay.alpha_composite(tile, (x, y))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def render(directory: Path, plan: dict) -> dict:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 24_000_000
    result = {"pageCount": 0, "pages": [], "customPages": []}

    def save(image, index: int, group: str) -> None:
        image.thumbnail((1200, 1800), Image.Resampling.LANCZOS)
        output = watermark_image(image, bool(plan["watermark"]))
        filename = f"{group}-{index}.webp"
        output.save(directory / filename, "WEBP", quality=82, method=3)
        result[group].append({"index": index, "width": output.width, "height": output.height, "file": filename})
        output.close()

    if plan.get("pdf"):
        import pypdfium2 as pdfium
        from app.services.material_lightweight_scanner import _scan_pdf

        path = directory / "source.pdf"
        if _scan_pdf(path) != "CLEAN":
            raise ValueError("PDF requires manual inspection")
        # Do not initialize forms; PDFium is built without V8/XFA support.
        with pdfium.PdfDocument(path) as document:
            result["pageCount"] = len(document)
            if not 0 < len(document) <= 10000:
                raise ValueError("unsupported page count")
            for n in range(min(len(document), plan["limit"])):
                page = document[n]
                try:
                    width, height = page.get_size()
                    if not all(math.isfinite(x) and 0 < x <= 100000 for x in (width, height)):
                        raise ValueError("invalid page dimensions")
                    scale = min(1200 / width, 1800 / height, 2)
                    bitmap = page.render(scale=scale, may_draw_forms=False)
                    try:
                        with bitmap.to_pil() as image:
                            save(image, n + 1, "pages")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
    for group, count in (("pages", len(plan["images"])), ("customPages", len(plan["customImages"]))):
        for n in range(count):
            with Image.open(directory / f"{group}-source-{n}") as image:
                if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError("image pixel limit exceeded")
                with ImageOps.exif_transpose(image) as oriented:
                    save(oriented, n + 1 if group == "pages" else 1001 + n, group)
    if not plan.get("pdf"):
        result["pageCount"] = len(result["pages"])
    return result


def main() -> int:
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024**2, 384 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
    resource.setrlimit(resource.RLIMIT_FSIZE, (5 * 1024**2, 5 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    directory = Path(sys.argv[1])
    try:
        _deny_network()
        result = render(directory, json.loads((directory / "plan.json").read_text()))
        (directory / "result.json").write_text(json.dumps(result))
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
