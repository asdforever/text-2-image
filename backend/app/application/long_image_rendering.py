"""长图的确定性排版与切片，不调用生成模型。"""
from io import BytesIO
from math import floor
from uuid import UUID
from zipfile import ZIP_STORED, ZipFile

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.errors import AppError

MAX_HEIGHT = 30000
MAX_PIXELS = 32_000_000
MAX_SOURCE_PIXELS = 24_000_000
MAX_INPUT_BYTES = 100 * 1024 * 1024


class Crop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top: int = Field(default=0, ge=0, le=45)
    right: int = Field(default=0, ge=0, le=45)
    bottom: int = Field(default=0, ge=0, le=45)
    left: int = Field(default=0, ge=0, le=45)


class LongImageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assetId: UUID
    crop: Crop = Field(default_factory=Crop)
    paddingTop: int = Field(default=0, ge=0, le=200)
    paddingBottom: int = Field(default=0, ge=0, le=200)


class LongImageRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    width: int = Field(default=750, ge=320, le=1600)
    gap: int = Field(default=0, ge=0, le=200)
    background: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    items: list[LongImageItem] = Field(min_length=1, max_length=20)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("请填写长图名称")
        return value.strip()


def rounded(value):
    return floor(value + 0.5)


def image_geometry(size, item, target_width):
    width, height = size
    left, top = rounded(width * item.crop.left / 100), rounded(height * item.crop.top / 100)
    right = max(left + 1, width - rounded(width * item.crop.right / 100))
    bottom = max(top + 1, height - rounded(height * item.crop.bottom / 100))
    return (left, top, right, bottom), max(1, rounded((bottom - top) * target_width / (right - left)))


def render_long_image(recipe: LongImageRecipe, bodies: list[bytes]):
    if len(bodies) != len(recipe.items) or sum(map(len, bodies)) > MAX_INPUT_BYTES:
        raise AppError("LONG_IMAGE_INPUT_LIMIT", "图片数量不匹配或输入图片合计超过 100 MiB", 400)
    geometry = []
    for data, item in zip(bodies, recipe.items):
        try:
            with Image.open(BytesIO(data)) as source:
                if source.width * source.height > MAX_SOURCE_PIXELS:
                    raise AppError("LONG_IMAGE_SOURCE_LIMIT", "单张来源图片超过 2400 万像素，请先缩小图片", 400)
                size = source.size
                if source.getexif().get(274) in {5, 6, 7, 8}:
                    size = (size[1], size[0])
                geometry.append(image_geometry(size, item, recipe.width))
        except AppError:
            raise
        except Exception as exc:
            raise AppError("LONG_IMAGE_SOURCE_INVALID", "来源图片无法读取，请更换图片", 400) from exc
    height = sum(h + item.paddingTop + item.paddingBottom for (_, h), item in zip(geometry, recipe.items)) + recipe.gap * (len(recipe.items) - 1)
    if height > MAX_HEIGHT or height * recipe.width > MAX_PIXELS:
        raise AppError("LONG_IMAGE_SIZE_LIMIT", "长图超过 30000 像素高度或 3200 万像素，请减少图片或缩小宽度", 400)
    canvas = Image.new("RGB", (recipe.width, height), recipe.background)
    y = 0
    try:
        for data, item, (box, h) in zip(bodies, recipe.items, geometry):
            y += item.paddingTop
            with Image.open(BytesIO(data)) as source:
                oriented = ImageOps.exif_transpose(source)
                cropped = oriented.crop(box)
                rgba = cropped.convert("RGBA")
                resized = rgba.resize((recipe.width, h), Image.Resampling.LANCZOS)
                canvas.paste(resized, (0, y), resized)
                resized.close(); rgba.close(); cropped.close(); oriented.close()
            y += h + item.paddingBottom + recipe.gap
        output = BytesIO()
        canvas.save(output, "PNG")
        return output.getvalue(), recipe.width, height
    except Exception as exc:
        raise AppError("LONG_IMAGE_RENDER_FAILED", "长图拼接失败，请检查图片后重试", 400) from exc
    finally:
        canvas.close()


def slice_long_image(body: bytes, height: int) -> bytes:
    if height < 256 or height > 10000:
        raise AppError("LONG_IMAGE_SLICE_INVALID", "切片高度应在 256–10000 像素之间", 400)
    output = BytesIO()
    with Image.open(BytesIO(body)) as image, ZipFile(output, "w", ZIP_STORED) as archive:
        for index, y in enumerate(range(0, image.height, height), 1):
            with image.crop((0, y, image.width, min(y + height, image.height))) as part:
                data = BytesIO()
                part.save(data, "PNG")
                archive.writestr(f"{index:03}.png", data.getvalue())
    return output.getvalue()
