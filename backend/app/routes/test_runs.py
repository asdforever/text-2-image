from fastapi import APIRouter, Request

from ..core.http import success_response


test_run_router = APIRouter()


@test_run_router.get("/api/test-runs")
async def list_test_runs(request: Request, prompt_version_id: str | None = None):
    return success_response(
        await request.app.state.test_run_service.list_runs(prompt_version_id)
    )


@test_run_router.post("/api/test-runs", status_code=201)
async def create_test_run(payload: dict, request: Request):
    return success_response(await request.app.state.test_run_service.create_run(payload))


@test_run_router.get("/api/test-runs/{test_run_id}")
async def get_test_run(test_run_id: str, request: Request):
    return success_response(await request.app.state.test_run_service.get_run(test_run_id))


@test_run_router.patch("/api/test-runs/{test_run_id}")
async def update_test_run(test_run_id: str, payload: dict, request: Request):
    return success_response(
        await request.app.state.test_run_service.update_run(test_run_id, payload)
    )


@test_run_router.delete("/api/test-runs/{test_run_id}", status_code=204)
async def delete_test_run(test_run_id: str, request: Request):
    await request.app.state.test_run_service.delete_run(test_run_id)
