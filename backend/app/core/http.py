"""统一的 HTTP 成功/错误契约。"""

from typing import Any

from fastapi.responses import JSONResponse

from .context import request_id_var


def success_response(data: Any) -> dict[str, Any]:
    return {"data": data, "requestId": request_id_var.get()}


def error_response(
    code: str,
    message: str,
    status_code: int,
    request_id: str | None = None,
) -> JSONResponse:
    resolved_request_id = request_id or request_id_var.get()
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "requestId": resolved_request_id,
        },
        headers={"X-Request-ID": resolved_request_id},
    )


def http_error_code(status_code: int) -> str:
    return {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        429: "RATE_LIMITED",
        503: "DEPENDENCY_NOT_READY",
    }.get(status_code, "HTTP_ERROR" if status_code < 500 else "INTERNAL_ERROR")


def public_http_message(status_code: int, detail: Any) -> str:
    if status_code >= 500:
        return "service dependency failed" if status_code == 503 else "internal server error"
    return str(detail)
