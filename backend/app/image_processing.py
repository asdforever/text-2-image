import hashlib
from io import BytesIO

from PIL import Image

from .core.errors import AppError


ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def inspect_image(data: bytes, declared_mime: str | None, max_bytes: int) -> tuple[str, int, int, str]:
    if len(data) > max_bytes:
        raise AppError("IMAGE_TOO_LARGE", "image exceeds size limit", 400)
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image_format = image.format or ""
            width, height = image.width, image.height
    except Exception as exc:
        raise AppError("INVALID_IMAGE", "file is not a valid image", 400) from exc
    mime = ALLOWED_FORMATS.get(image_format)
    if mime is None:
        raise AppError("UNSUPPORTED_IMAGE_MIME", "only JPG, PNG and WebP are supported", 400)
    if declared_mime and declared_mime != mime:
        raise AppError("MIME_MISMATCH", "declared image type does not match content", 400)
    return mime, width, height, hashlib.sha256(data).hexdigest()


def thumbnail_bytes(data: bytes, max_size: int = 512) -> bytes:
    with Image.open(BytesIO(data)) as image:
        image.thumbnail((max_size, max_size))
        output = BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=85)
        return output.getvalue()
