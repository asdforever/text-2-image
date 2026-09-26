import asyncio
import asyncpg
from backend.app.core.config import get_settings

async def create_database():
    cfg = get_settings()

    # 连接到默认的 postgres 数据库
    conn = await asyncpg.connect(
        host=cfg.pg_host,
        port=cfg.pg_port,
        user=cfg.pg_user,
        password=cfg.pg_password,
        database='postgres'
    )

    try:
        # 检查数据库是否存在
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            cfg.pg_database
        )

        if exists:
            print(f"Database '{cfg.pg_database}' already exists")
        else:
            # 创建数据库
            await conn.execute(f'CREATE DATABASE "{cfg.pg_database}"')
            print(f"Database '{cfg.pg_database}' created successfully")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(create_database())
