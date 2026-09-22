from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/live")
def live() -> dict:
    settings = get_settings()
    return {
        "status": "live",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "status": "ready",
        "database": "reachable",
        "premium_slice_enabled": settings.premium_slice_enabled,
        "auth_provider": settings.auth_provider,
        "efata_mode": settings.efata_mode,
        "efata_contract_version": settings.efata_contract_version,
    }
