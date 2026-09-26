import asyncio
from uuid import UUID

import httpx
from fastapi import Request

from backend.app.core.config import Settings
from backend.app.core.identity import get_identity_context
from backend.app.main import create_app


ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WORKSPACE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def test_business_dependency_uses_server_context_and_ignores_client_scope() -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings(
                local_actor_id=ACTOR_ID,
                local_workspace_id=WORKSPACE_ID,
                local_role="owner",
            )
        )

        @app.get("/test/identity-context")
        async def read_context(request: Request):
            context = get_identity_context(request)
            return {"actorId": str(context.actor_id), "workspaceId": str(context.workspace_id), "role": context.role}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/test/identity-context",
                headers={"X-Actor-Id": str(UUID(int=1)), "X-Workspace-Id": str(UUID(int=2))},
            )

        assert response.status_code == 200
        assert response.json() == {"actorId": str(ACTOR_ID), "workspaceId": str(WORKSPACE_ID), "role": "owner"}

    asyncio.run(run())
