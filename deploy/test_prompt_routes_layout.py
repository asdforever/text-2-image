"""提示词路由必须挂在一个独立 router 上，并且由 main 显式注册。

这条约束原来是前端仓库里的 prompt-marketplace 契约测试在守。
前后端分仓后前端读不到后端源码，所以搬到这边来。

改动 prompts 路由的注册方式时，前端那边的调用契约可能同时受影响。
"""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_prompt_routes_live_in_a_dedicated_fastapi_router() -> None:
    routes = (ROOT / "backend" / "app" / "routes" / "prompts.py").read_text(encoding="utf-8")
    assert "APIRouter" in routes
    assert "prompt-templates" in routes

    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert "include_router(prompt_router" in main
    assert '@app.get("/api/prompt-templates"' not in main
