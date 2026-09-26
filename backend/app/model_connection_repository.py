"""不可变模型连接版本，凭据与普通生成配置分开存放。"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import text


@dataclass(frozen=True)
class ModelConnectionRecord:
    id: UUID
    workspace_id: UUID
    base_url: str
    model_name: str
    protocol: str
    encrypted_key: bytes = field(repr=False)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryModelConnectionRepository:
    def __init__(self):
        self.records = {}

    async def get(self, connection_id, workspace_id):
        return self.records.get((workspace_id, connection_id))

    async def list(self, workspace_id):
        return [record for (workspace, _), record in self.records.items() if workspace == workspace_id]

    async def insert(self, record):
        return self.records.setdefault((record.workspace_id, record.id), record)


class PostgresModelConnectionRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def get(self, connection_id, workspace_id):
        async with self.sessions() as db:
            row = (await db.execute(text("SELECT * FROM generation_config.model_connections WHERE id=:id AND workspace_id=:workspace"), {"id":connection_id,"workspace":workspace_id})).mappings().first()
            return ModelConnectionRecord(**row) if row else None

    async def list(self, workspace_id):
        async with self.sessions() as db:
            rows = (await db.execute(text("SELECT * FROM generation_config.model_connections WHERE workspace_id=:workspace ORDER BY created_at DESC"), {"workspace":workspace_id})).mappings()
            return [ModelConnectionRecord(**row) for row in rows]

    async def insert(self, record):
        async with self.sessions() as db, db.begin():
            await db.execute(text("""INSERT INTO generation_config.model_connections(id,workspace_id,base_url,model_name,protocol,encrypted_key,created_at)
                VALUES (:id,:workspace_id,:base_url,:model_name,:protocol,:encrypted_key,:created_at) ON CONFLICT (id) DO NOTHING"""), vars(record))
        return await self.get(record.id, record.workspace_id)
