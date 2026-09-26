"""画布版本聚合：所有版本变更均在同一记录的事务锁内执行。"""
from copy import deepcopy
import json
from sqlalchemy import text

from .core.errors import AppError


class MemoryCanvasGenerationRepository:
    def __init__(self):
        self.tracks = {}

    async def list(self, project_id, workspace_id):
        return deepcopy([state for (workspace, project, _), state in self.tracks.items() if project == project_id and workspace == workspace_id])

    async def change(self, project_id, workspace_id, step_id, initial, action):
        key = (workspace_id, project_id, step_id)
        state = deepcopy(self.tracks.get(key, initial))
        if state is None:
            raise AppError("CANVAS_TRACK_NOT_FOUND", "生成版本记录不存在", 404)
        result = action(state)
        self.tracks[key] = state
        return deepcopy(result)


class PostgresCanvasGenerationRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def list(self, project_id, workspace_id):
        async with self.sessions() as db:
            rows = await db.execute(text("SELECT state FROM project_workbench.canvas_generation_tracks WHERE project_id=:project AND workspace_id=:workspace ORDER BY step_id"), {"project": project_id, "workspace": workspace_id})
            return [deepcopy(row[0]) for row in rows]

    async def change(self, project_id, workspace_id, step_id, initial, action):
        params = {"project": project_id, "workspace": workspace_id, "step": step_id}
        async with self.sessions() as db, db.begin():
            if initial is not None:
                await db.execute(text("INSERT INTO project_workbench.canvas_generation_tracks (workspace_id, project_id, step_id, state) VALUES (:workspace, :project, :step, CAST(:state AS jsonb)) ON CONFLICT DO NOTHING"), {**params, "state": json.dumps(initial)})
            state = await db.scalar(text("SELECT state FROM project_workbench.canvas_generation_tracks WHERE workspace_id=:workspace AND project_id=:project AND step_id=:step FOR UPDATE"), params)
            if state is None:
                raise AppError("CANVAS_TRACK_NOT_FOUND", "生成版本记录不存在", 404)
            result = action(state)
            await db.execute(text("UPDATE project_workbench.canvas_generation_tracks SET state=CAST(:state AS jsonb), updated_at=now() WHERE workspace_id=:workspace AND project_id=:project AND step_id=:step"), {**params, "state": json.dumps(state)})
            return deepcopy(result)
