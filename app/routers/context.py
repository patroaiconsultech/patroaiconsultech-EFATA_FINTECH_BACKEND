from fastapi import APIRouter, Depends

from app.security import SecurityContext, require_security_context

router = APIRouter(prefix="/api/v1", tags=["context"])


@router.get("/me")
def me(context: SecurityContext = Depends(require_security_context)) -> dict:
    return {
        "user_id": context.user_id,
        "tenant_id": context.tenant_id,
        "membership_id": context.membership_id,
        "role": context.role,
    }
