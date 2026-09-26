from fastapi import APIRouter, Request

from ..core.http import success_response


product_router = APIRouter(prefix="/api/test-product-libraries")


@product_router.get("")
async def list_product_libraries(request: Request):
    return success_response(await request.app.state.product_service.list_libraries())


@product_router.post("", status_code=201)
async def create_product_library(payload: dict, request: Request):
    return success_response(await request.app.state.product_service.create_library(payload))


@product_router.get("/{library_id}")
async def get_product_library(library_id: str, request: Request):
    return success_response(await request.app.state.product_service.get_library(library_id))


@product_router.patch("/{library_id}")
async def update_product_library(library_id: str, payload: dict, request: Request):
    return success_response(
        await request.app.state.product_service.update_library(library_id, payload)
    )


@product_router.delete("/{library_id}", status_code=204)
async def delete_product_library(library_id: str, request: Request):
    await request.app.state.product_service.delete_library(library_id)


@product_router.get("/{library_id}/products")
async def list_products(library_id: str, request: Request):
    return success_response(await request.app.state.product_service.list_products(library_id))


@product_router.post("/{library_id}/products", status_code=201)
async def create_product(library_id: str, request: Request):
    form = await request.form()
    file = form.get("file")
    upload = file if hasattr(file, "read") and hasattr(file, "filename") else None
    payload = {
        "name": form.get("name"),
        "productType": form.get("productType"),
        "testRunId": form.get("testRunId"),
        "projectId": form.get("projectId"),
        "metadata": form.get("metadata"),
        "fileData": await upload.read() if upload else None,
        "filename": upload.filename if upload else None,
        "contentType": upload.content_type if upload else None,
    }
    return success_response(
        await request.app.state.product_service.create_product(library_id, payload)
    )


@product_router.delete(
    "/{library_id}/products/{product_id}", status_code=204
)
async def delete_product(library_id: str, product_id: str, request: Request):
    await request.app.state.product_service.delete_product(library_id, product_id)
