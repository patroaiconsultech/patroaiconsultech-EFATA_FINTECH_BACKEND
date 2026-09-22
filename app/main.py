from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errors import ApiError, api_error_handler
from app.logging_config import configure_logging
from app.middleware import request_context_middleware
from app.routers import consent_ledger, context, documents, health, leads, marketplace, opportunities, qualification, reconciliation, reconciliation_persistent, representations, risk, viability


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    allowed_origins = [
        origin.strip()
        for origin in settings.cors_allowed_origins.split(",")
        if origin.strip()
    ]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-User-ID",
                "X-Tenant-ID",
                "X-Request-ID",
                "X-Correlation-ID",
                "If-Match",
            ],
            expose_headers=["X-Request-ID", "X-Correlation-ID", "X-Duration-Ms"],
        )

    app.middleware("http")(request_context_middleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(health.router)
    app.include_router(context.router)

    if settings.premium_slice_enabled:
        app.include_router(leads.router)
        app.include_router(representations.router)
        app.include_router(opportunities.router)
        app.include_router(documents.router)
        app.include_router(qualification.router)
        app.include_router(marketplace.router)
        app.include_router(risk.router)
        app.include_router(reconciliation.router)
        app.include_router(reconciliation_persistent.router)
        app.include_router(consent_ledger.router)
        app.include_router(viability.router)

    return app


app = create_app()
