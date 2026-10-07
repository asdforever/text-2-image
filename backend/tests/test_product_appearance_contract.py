from backend.app.application.product_appearance import (
    ALL_PRODUCT_APPEARANCE_MODULE_IDS,
    product_appearance_contract,
    product_appearance_contract_prompt,
)


def test_every_catalog_module_has_an_explicit_product_appearance_contract() -> None:
    expected = {
        "hero-kv", "hero-overview", "hero-detail", "hero-scene", "hero-colors",
        "hero-compare", "hero-package", "hero-benefit",
        "suite-hero", "suite-benefit", "suite-scene", "suite-angle", "suite-mood",
        "suite-detail", "suite-story", "suite-size", "suite-effect", "suite-spec",
        "suite-craft", "suite-accessory", "suite-series", "suite-ingredient",
        "suite-support", "suite-guide", "suite-buyer", "suite-creator",
    }

    assert set(ALL_PRODUCT_APPEARANCE_MODULE_IDS) == expected
    assert all(product_appearance_contract(module_id) for module_id in expected)


def test_product_appearance_contracts_encode_behavioral_and_omission_rules() -> None:
    assert "必须出现完整产品" in product_appearance_contract("hero-kv")
    assert "必须处于使用状态" in product_appearance_contract("suite-scene")
    assert "默认不出现产品" in product_appearance_contract("suite-craft")
    assert "不得再次完整摆拍" in product_appearance_contract("suite-detail")


def test_contract_prompt_is_explicitly_keyed_by_module_id() -> None:
    prompt = product_appearance_contract_prompt()

    assert "模块级产品出场契约" in prompt
    assert "suite-scene" in prompt
    assert "hero-benefit" in prompt
    assert "先决定产品是否出场" in prompt
    assert "再决定产品行为" in prompt
