import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from backend.app.project_repository import PostgresProjectRepository


class _Result:
    def mappings(self):
        return self

    def first(self):
        return {
            "id": UUID(int=1),
            "project_id": UUID(int=2),
            "object_id": UUID(int=3),
            "kind": "source",
            "source_asset_id": None,
            "generation_snapshot_id": None,
            "state": "available",
            "created_at": None,
            "source_kind": "asset_library",
            "source_library_id": "library-1",
            "source_resource_id": "resource-1",
            "source_resource_version_id": "version-1",
            "source_snapshot": {"origin": "shared"},
        }


class _Session:
    def __init__(self):
        self.params = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, _statement, params):
        self.params = params
        return _Result()


def test_postgres_project_asset_snapshot_is_encoded_for_jsonb() -> None:
    async def run() -> None:
        session = _Session()
        repository = PostgresProjectRepository(lambda: session)

        await repository.create_asset(
            UUID(int=2),
            UUID(int=3),
            "source",
            source_kind="asset_library",
            source_library_id="library-1",
            source_resource_id="resource-1",
            source_resource_version_id="version-1",
            source_snapshot={"origin": "shared"},
        )

        assert session.params["source_snapshot"] == '{"origin": "shared"}'

    asyncio.run(run())
