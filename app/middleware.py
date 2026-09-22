import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger("fintech.request")


async def request_context_middleware(request: Request, call_next):
    started = perf_counter()
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.correlation_id = (
        request.headers.get("X-Correlation-ID")
        or request.state.request_id
    )

    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = round((perf_counter() - started) * 1000, 3)
        security_context = getattr(request.state, "security_context", None)

        logger.info(
            "HTTP_REQUEST_COMPLETED",
            extra={
                "request_id": request.state.request_id,
                "correlation_id": request.state.correlation_id,
                "tenant_id": getattr(security_context, "tenant_id", None),
                "user_id": getattr(security_context, "user_id", None),
                "auth_provider": getattr(security_context, "auth_provider", None),
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "event_code": "HTTP_REQUEST_COMPLETED",
            },
        )

        if "response" in locals():
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["X-Correlation-ID"] = request.state.correlation_id
            response.headers["X-Duration-Ms"] = str(duration_ms)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            response.headers["Cache-Control"] = "no-store"
            if request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
