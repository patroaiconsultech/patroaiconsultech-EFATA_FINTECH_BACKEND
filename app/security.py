from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_provider import AuthIdentity, get_auth_provider
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Membership, Tenant, User


@dataclass(frozen=True)
class SecurityContext:
    user_id: str
    tenant_id: str
    membership_id: str
    role: str
    auth_provider: str
    external_subject: str | None = None


class SecurityContextFactory:
    def create(
        self,
        *,
        identity: AuthIdentity,
        db: Session,
    ) -> SecurityContext:
        user = db.scalar(
            select(User).where(
                User.user_id == identity.user_id,
                User.status == "ACTIVE",
            )
        )
        tenant = db.scalar(
            select(Tenant).where(
                Tenant.tenant_id == identity.tenant_id,
                Tenant.status == "ACTIVE",
            )
        )
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == identity.user_id,
                Membership.tenant_id == identity.tenant_id,
                Membership.status == "ACTIVE",
            )
        )

        if user is None or tenant is None or membership is None:
            raise ApiError(
                403,
                "PRINCIPAL_NOT_PROVISIONED",
                "Acesso não autorizado.",
            )

        # Effective authorization comes from the local canonical membership.
        # Token asserted roles never elevate privileges by themselves.
        return SecurityContext(
            user_id=user.user_id,
            tenant_id=tenant.tenant_id,
            membership_id=membership.membership_id,
            role=membership.role,
            auth_provider=identity.provider,
            external_subject=identity.external_subject,
        )


def require_security_context(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SecurityContext:
    provider = get_auth_provider(settings)
    identity = provider.authenticate(request)
    context = SecurityContextFactory().create(identity=identity, db=db)
    request.state.security_context = context
    return context


def require_client_authorizer(
    context: SecurityContext = Depends(require_security_context),
) -> SecurityContext:
    if context.role not in {"CLIENT_ADMIN"}:
        raise ApiError(403, "ROLE_NOT_ALLOWED", "Acesso não autorizado.")
    return context


def require_analyst(
    context: SecurityContext = Depends(require_security_context),
) -> SecurityContext:
    if context.role not in {"ANALYST", "PLATFORM_ADMIN"}:
        raise ApiError(403, "ROLE_NOT_ALLOWED", "Acesso não autorizado.")
    return context
