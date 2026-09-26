"""目录与生成参数共用的分辨率名称。"""
RESOLUTION_LEVELS = {"标准 1K": 1024, "高清 2K": 2048, "超清 4K": 4096}
RESOLUTION_ALIASES = {"1K": "标准 1K", "2K": "高清 2K", "4K": "超清 4K"}


def normalize_resolution(value: str) -> str:
    value = value.strip()
    return RESOLUTION_ALIASES.get(value, value)
