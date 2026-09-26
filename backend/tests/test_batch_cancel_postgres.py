"""在外层事务内验证真实 PostgreSQL 取消路径，所有测试数据最终回滚。"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.batch_generation_repository import PostgresBatchGenerationRepository
from backend.app.core.config import get_settings
from backend.app.db import create_engine


@pytest.mark.asyncio
@pytest.mark.parametrize("slot_status", ["queued", "leased", "dispatching"])
async def test_cancel_persists_slots_attempts_and_batch_without_sql_type_conflict(slot_status):
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL")
    engine = create_engine(settings.database_url)
    workspace, project, obj, asset, batch, module, slot, lease = [uuid4() for _ in range(8)]
    now = datetime.now(timezone.utc)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("INSERT INTO suite_workbench.workspaces (id,name) VALUES (:id,'取消批次事务测试')"), {"id":workspace})
                await connection.execute(text("INSERT INTO project_workbench.projects(id,workspace_id,name) VALUES (:id,:workspace,'取消测试')"), {"id":project,"workspace":workspace})
                await connection.execute(text("INSERT INTO project_workbench.asset_objects(id,workspace_id,storage_key,original_filename,media_type,byte_size,width,height,sha256) VALUES (:id,:workspace,:key,'test.png','image/png',1,1,1,:sha)"), {"id":obj,"workspace":workspace,"key":f"cancel-tests/{obj}","sha":"a"*64})
                await connection.execute(text("INSERT INTO project_workbench.project_assets(id,project_id,object_id,kind) VALUES (:id,:project,:obj,'source')"), {"id":asset,"project":project,"obj":obj})
                await connection.execute(text("INSERT INTO project_workbench.generation_batches(id,workspace_id,project_id,source_asset_id,status,compile_idempotency_key,compile_fingerprint,snapshot) VALUES (:id,:workspace,:project,:asset,'queued',:key,:sha,'{}')"), {"id":batch,"workspace":workspace,"project":project,"asset":asset,"key":str(batch),"sha":"b"*64})
                await connection.execute(text("INSERT INTO project_workbench.generation_module_tasks(id,batch_id,module_key,position,requested_image_count,snapshot) VALUES (:id,:batch,'main-image',1,1,'{}')"), {"id":module,"batch":batch})
                await connection.execute(text("INSERT INTO project_workbench.generation_image_slots(id,batch_id,module_task_id,ordinal,status,lease_token) VALUES (:id,:batch,:module,1,:status,:lease)"), {"id":slot,"batch":batch,"module":module,"status":slot_status,"lease":lease if slot_status != "queued" else None})
                if slot_status != "queued":
                    await connection.execute(text("INSERT INTO project_workbench.generation_slot_attempts(id,slot_id,attempt_no,status,lease_token,worker_id) VALUES (:id,:slot,1,:status,:lease,'test')"), {"id":uuid4(),"slot":slot,"status":slot_status,"lease":lease})
                repository = PostgresBatchGenerationRepository(async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode="create_savepoint"))
                cancelled = await repository.cancel_batch(batch, workspace, now=now)
                expected = "cancel_requested" if slot_status == "dispatching" else "cancelled"
                assert cancelled.status == expected
                assert cancelled.completed_at == (None if slot_status == "dispatching" else now)
                detail = await repository.get_batch_detail(batch, workspace)
                assert detail.slots[0].status == expected
                if slot_status == "leased":
                    assert await connection.scalar(text("SELECT status FROM project_workbench.generation_slot_attempts WHERE slot_id=:slot"), {"slot":slot}) == "cancelled"
                # 重复取消不报错，也不会改变已发送请求的等待取消状态。
                assert (await repository.cancel_batch(batch, workspace, now=now)).status == expected
            finally:
                await transaction.rollback()
        async with engine.connect() as check:
            assert await check.scalar(text("SELECT count(*) FROM suite_workbench.workspaces WHERE id=:id"), {"id":workspace}) == 0
    finally:
        await engine.dispose()
