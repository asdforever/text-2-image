from copy import deepcopy

import pytest

from backend.app.core.errors import AppError
from backend.app.generation_config_catalog import (
    create_default_generation_config,
    normalize_generation_config,
)


def test_default_generation_config_contains_concrete_markets_models_and_fixed_modules() -> None:
    config = create_default_generation_config()

    assert {market["id"] for market in config["markets"]} >= {"taobao", "jd", "amazon"}
    assert {market["marketScope"] for market in config["markets"]} == {
        "domestic",
        "overseas",
    }
    assert all(model["resolutions"] for model in config["models"])
    assert config["heroModules"][0]["id"] == "hero-kv"
    assert config["suiteModules"][0]["id"] == "suite-hero"


def test_generation_config_normalization_trims_values_and_rebuilds_binding_slots() -> None:
    config = create_default_generation_config()
    config["markets"][0]["id"] = "  taobao  "
    config["markets"][0]["label"] = "  淘宝  "
    config["models"][0]["resolutions"] = [" 标准 1K ", "标准 1K", "高清 2K"]
    config["marketBindings"]["orphan"] = None

    normalized = normalize_generation_config(config)

    assert normalized["markets"][0]["id"] == "taobao"
    assert normalized["markets"][0]["label"] == "淘宝"
    assert normalized["models"][0]["resolutions"] == ["标准 1K", "高清 2K"]
    assert set(normalized["marketBindings"]) == {
        market["id"] for market in normalized["markets"]
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["markets"].append({"id": "domestic", "label": "国内", "marketScope": "domestic", "platforms": "国内", "guidance": "规范", "defaultLanguage": "中文"}), "具体电商平台"),
        (lambda value: value["models"][0].update({"resolutions": []}), "至少支持一种分辨率"),
        (lambda value: value["styleCategories"][0]["styles"].extend([
            {"id": "fourth", "label": "第四种", "description": "第四种风格"},
            {"id": "fifth", "label": "第五种", "description": "第五种风格"},
        ]), "最多 4 个风格"),
        (lambda value: value["heroModules"].__setitem__(0, {"id": "hero-bad", "label": "错误模块", "description": "说明", "mode": "suite"}), "主图模块类型必须为 hero"),
        (lambda value: value["suiteModules"].clear(), "至少需要一个详情页模块"),
    ],
)
def test_generation_config_validation_rejects_invalid_catalogs(mutation, message: str) -> None:
    config = deepcopy(create_default_generation_config())
    mutation(config)

    with pytest.raises(AppError) as caught:
        normalize_generation_config(config)

    assert caught.value.code == "GENERATION_CONFIG_INVALID"
    assert message in caught.value.message


def test_generation_config_validation_rejects_non_numeric_client_version() -> None:
    config = create_default_generation_config()
    config["version"] = "not-a-number"

    with pytest.raises(AppError) as caught:
        normalize_generation_config(config)

    assert caught.value.code == "GENERATION_CONFIG_INVALID"
