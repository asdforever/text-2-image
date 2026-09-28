from copy import deepcopy

import pytest

from backend.app.application.runtime_module_catalog import runtime_module_catalog, runtime_catalog_snapshot
from backend.app.core.errors import AppError


def test_freeform_is_available_without_changing_published_config():
    config = {"heroModules": [{"id": "hero-kv", "mode": "hero"}], "suiteModules": []}
    before = deepcopy(config)
    hero = runtime_module_catalog(config, "hero")
    assert [m["id"] for m in hero] == ["hero-kv", "hero-freeform"]
    assert runtime_module_catalog(config, "suite")[0]["id"] == "suite-freeform"
    hero[0]["id"] = "changed"
    assert config == before
    assert runtime_catalog_snapshot(config)["contentSha256"] == runtime_catalog_snapshot(before)["contentSha256"]


def test_existing_freeform_definition_is_not_duplicated():
    config = {"heroModules": [{"id": "hero-freeform", "mode": "hero", "label": "定制"}]}
    assert runtime_module_catalog(config, "hero") == config["heroModules"]
    config["heroModules"][0]["mode"] = "suite"
    with pytest.raises(AppError) as exc:
        runtime_module_catalog(config, "hero")
    assert exc.value.code == "RUNTIME_MODULE_CATALOG_INVALID"
