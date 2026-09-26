"""记录生图执行进程心跳，用于区分正常排队与执行器离线。"""
from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE project_workbench.generation_worker_heartbeats (
        worker_id text PRIMARY KEY,
        last_seen_at timestamptz NOT NULL DEFAULT now()
    )""")


def downgrade():
    op.execute("DROP TABLE project_workbench.generation_worker_heartbeats")
