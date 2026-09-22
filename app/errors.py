from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "meta": {
                "request_id": request_id,
                "correlation_id": correlation_id,
            },
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": [],
            },
        },
    )
