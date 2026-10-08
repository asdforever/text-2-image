from io import BytesIO

from PIL import Image

from .errors import AppError


def transparent_png(data: bytes) -> bytes:
    """保留真实透明度，拒绝白底、棋盘格与空白结果。"""
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGBA")
    alpha = image.getchannel("A")
    low, high = alpha.getextrema()
    border = [alpha.getpixel((x, y)) for x in range(image.width) for y in {0, image.height - 1}]
    border.extend(alpha.getpixel((x, y)) for y in range(image.height) for x in {0, image.width - 1})
    if low != 0 or high == 0 or sum(value == 0 for value in border) < len(border) / 2:
        raise AppError("TRANSPARENT_BACKGROUND_INVALID", "模型未返回真实透明背景 PNG，请检查模型是否支持透明输出后重试", 502)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
