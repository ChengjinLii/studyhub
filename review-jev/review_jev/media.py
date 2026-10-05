from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from .schemas import MAX_IMAGE_BYTES, Content

DATA_URI = re.compile(r"^data:image/(png|jpeg|webp);base64,(.+)$", re.DOTALL)
FORMATS = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}
MAX_PIXELS = 12_000_000
MAX_NORMALIZED_BYTES = 8 * 1024 * 1024


class InvalidImage(ValueError):
    pass


@dataclass(frozen=True)
class PreparedImages:
    media: list[dict[str, str]]
    sha256: dict[str, str]


def prepare_images(content: Content) -> PreparedImages:
    items, hashes = [], {}
    for item in content.images:
        match = DATA_URI.fullmatch(item.data)
        if match is None:
            raise InvalidImage("only base64 PNG, JPEG, or WebP data URIs are accepted")
        try:
            raw = base64.b64decode(match[2], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidImage("invalid base64 image") from exc
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise InvalidImage("each image must be between 1 byte and 4 MiB")
        hashes[item.id] = hashlib.sha256(raw).hexdigest()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format != FORMATS[match[1]]:
                        raise InvalidImage("declared image format does not match its bytes")
                    if image.width * image.height > MAX_PIXELS:
                        raise InvalidImage("each image must be at most 12 megapixels")
                    if getattr(image, "n_frames", 1) != 1:
                        raise InvalidImage("animated images are not supported")
                    image.load()
                    image = ImageOps.exif_transpose(image)
                    # Flatten alpha so hidden RGB pixels are not treated as visible content.
                    if "A" in image.getbands() or "transparency" in image.info:
                        rgba = image.convert("RGBA")
                        rgb = Image.new("RGB", image.size, "white")
                        rgb.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        rgb = image.convert("RGB")
                    encoded = io.BytesIO()
                    rgb.save(encoded, format="PNG")
                    normalized = encoded.getvalue()
                    if len(normalized) > MAX_NORMALIZED_BYTES:
                        raise InvalidImage("decoded image is too large; provide a smaller image")
        except InvalidImage:
            raise
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ) as exc:
            raise InvalidImage("image cannot be safely decoded") from exc
        uri = "data:image/png;base64," + base64.b64encode(normalized).decode("ascii")
        items.append({"type": "image", "data": uri})
    return PreparedImages(items, hashes)
