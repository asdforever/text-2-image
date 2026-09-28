"""Execution modules projected over immutable workspace configuration."""
from copy import deepcopy
from hashlib import sha256
import json

from ..core.errors import AppError


def runtime_module_catalog(config: dict, mode: str) -> list[dict]:
    if mode not in ("hero", "suite"):
        raise AppError("RUNTIME_MODULE_CATALOG_INVALID", "图片任务类型无效", 500)
    modules = deepcopy(config.get(f"{mode}Modules", []))
    module_id = f"{mode}-freeform"
    matching = [item for item in modules if item.get("id") == module_id]
    if len(matching) > 1 or any(item.get("mode") != mode for item in matching):
        raise AppError("RUNTIME_MODULE_CATALOG_INVALID", "自由创意模块配置无效", 500)
    if not matching:
        modules.append({"id": module_id, "mode": mode, "label": "自由创意",
                        "description": "按本图信息目标选择表达方式，商品按需出场"})
    return modules


def runtime_catalog_snapshot(config: dict) -> dict:
    value = {"version": "runtime-modules-v1", "heroModules": runtime_module_catalog(config, "hero"),
             "suiteModules": runtime_module_catalog(config, "suite")}
    value["contentSha256"] = sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return value
