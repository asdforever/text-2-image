from hashlib import sha256
from uuid import UUID

from ..core.errors import AppError
from .hero_generation_ports import ImageEditInput

MAX_AUXILIARY_IMAGES = 4


def normalize_auxiliary_ids(value, primary_id=None):
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise AppError("REVERSE_PRODUCT_IMAGES_INVALID", "辅助商品图必须为图片列表", 400)
    try:
        ids = list(dict.fromkeys(str(UUID(str(item))) for item in value))
    except (ValueError, TypeError):
        raise AppError("REVERSE_PRODUCT_IMAGES_INVALID", "辅助商品图标识无效", 400) from None
    ids = [item for item in ids if item != str(primary_id)]
    if len(ids) > MAX_AUXILIARY_IMAGES:
        raise AppError("REVERSE_PRODUCT_IMAGES_INVALID", "最多选择四张辅助商品图", 400)
    return ids


def product_view_guidance(count):
    if count <= 1:
        return ""
    return (f"第1张是商品主图，第2至第{count}张是同一商品的辅助视角与细节图，共同作为唯一产品外观依据。"
            "这些图片不是多个商品，不拼成多件套装，不混合不同视角的轮廓和部件；从最清楚的可见视角确认结构，保持同一商品身份。"
            "主图确定整体外观，辅助图补充侧面、背面和局部细节，最终朝向与机位服从当前页面构图；各图矛盾或不可见的信息不擅自补造。")


def image_snapshot(asset_id, obj, stored):
    return {"assetId": str(asset_id), "filename": obj.original_filename,
            "mimeType": obj.media_type, "sha256": sha256(stored.data).hexdigest()}


async def load_product_images(assets, project_id, asset_ids):
    inputs, snapshots = [], []
    for asset_id in asset_ids:
        asset, obj = await assets.get_asset_details(project_id, UUID(str(asset_id)))
        if getattr(asset, "kind", "source") not in {"source", "white_background"} or getattr(asset, "state", "available") != "available":
            raise AppError("REVERSE_PRODUCT_IMAGES_INVALID", "商品素材必须是当前项目中可用的原图、白底图或透明图", 400)
        stored = await assets.get_preview(project_id, asset.id)
        inputs.append(ImageEditInput(stored.data, obj.media_type, obj.original_filename))
        snapshots.append(image_snapshot(asset.id, obj, stored))
    return inputs, snapshots
