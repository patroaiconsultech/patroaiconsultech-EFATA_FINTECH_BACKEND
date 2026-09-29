from __future__ import annotations

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class M2MApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: list[dict] | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


def _state_value(request: Request, name: str, default=None):
    return getattr(request.state, name, default)


def _error_envelope(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict] | None = None,
) -> JSONResponse:
    request.state.m2m_error_code = code
    context = _state_value(request, "m2m_context")
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "request_id": _state_value(request, "request_id"),
            "execution_id": _state_value(request, "m2m_execution_id"),
            "correlation_id": _state_value(request, "correlation_id"),
            "tenant_id": getattr(context, "tenant_id", None),
            "capability": _state_value(request, "m2m_requested_capability"),
            "status": "failed",
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            },
            "meta": {
                "api_version": "v1",
                "contract_version": "m2m-r1",
            },
        },
    )


async def m2m_error_handler(request: Request, exc: M2MApiError) -> JSONResponse:
    return _error_envelope(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def m2m_request_validation_handler(
    request: Request,
    exc: RequestValidationError,
):
    if not request.url.path.startswith("/api/v1/m2m/"):
        return await request_validation_exception_handler(request, exc)

    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "reason": error.get("type", "validation_error"),
        }
        for error in exc.errors()
    ]
    return _error_envelope(
        request,
        status_code=422,
        code="M2M_VALIDATION_ERROR",
        message="Requisição M2M inválida.",
        details=details,
    )
