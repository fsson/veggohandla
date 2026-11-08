"""Shrink recipe images so the data directory doesn't bloat."""

from __future__ import annotations

import io
import uuid

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1200


def normalized(data: bytes) -> ContentFile | None:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=82)
    return ContentFile(out.getvalue(), name=f"{uuid.uuid4().hex}.webp")
