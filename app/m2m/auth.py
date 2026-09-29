from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.m2m.context import M2MContext, M2MContextFactory, M2MIdentity, ensure_request_ids
from app.m2m.errors import M2MApiError


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        # OAuth scopes are commonly space-separated. The contract capabilities
        # claim may also arrive as a list.
        return tuple(part for part in value.replace(",", " ").split() if part)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


class M2MTokenValidator(Protocol):
    def validate(self, token: str) -> M2MIdentity:
        ...


class OidcIntrospectionM2MTokenValidator:
    def __init__(self, settings: Settings):
        self.settings = settings
        required = {
            "m2m_introspection_endpoint": settings.m2m_introspection_endpoint,
            "m2m_introspection_client_id": settings.m2m_introspection_client_id,
            "m2m_introspection_client_secret": settings.m2m_introspection_client_secret,
            "m2m_issuer": settings.m2m_issuer,
            "m2m_audience": settings.m2m_audience,
            "m2m_allowed_client_id": settings.m2m_allowed_client_id,
            "m2m_service_principal_id": settings.m2m_service_principal_id,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise M2MApiError(
                503,
                "M2M_INTERNAL_ERROR",
                "A autenticação M2M não está configurada.",
            )

    def validate(self, token: str) -> M2MIdentity:
        try:
            response = httpx.post(
                self.settings.m2m_introspection_endpoint,
                data={"token": token},
                auth=(
                    self.settings.m2m_introspection_client_id,
                    self.settings.m2m_introspection_client_secret,
                ),
                timeout=self.settings.m2m_http_timeout_seconds,
            )
            response.raise_for_status()
            claims: dict[str, Any] = response.json()
        except M2MApiError:
            raise
        except Exception as exc:
            raise M2MApiError(
                503,
                "M2M_UPSTREAM_UNAVAILABLE",
                "O provedor de identidade M2M está indisponível.",
            ) from exc

        if not claims.get("active"):
            raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Credencial M2M inválida.")

        issuer = str(claims.get("iss") or "").strip()
        if issuer != str(self.settings.m2m_issuer):
            raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Credencial M2M inválida.")

        audience = claims.get("aud", [])
        audience = [audience] if isinstance(audience, str) else list(audience or [])
        if self.settings.m2m_audience not in audience:
            raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Credencial M2M inválida.")

        subject = str(claims.get("sub") or "").strip()
        client_id = str(claims.get("client_id") or claims.get("azp") or "").strip()
        credential_id = str(claims.get("jti") or "").strip()
        source_environment = str(claims.get("env") or "").strip()

        if (
            not subject
            or not client_id
            or client_id != self.settings.m2m_allowed_client_id
            or not credential_id
            or source_environment != self.settings.app_env
        ):
            raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Credencial M2M inválida.")

        tenant_scope = _as_str_tuple(claims.get("tenant_scope"))
        capabilities = _as_str_tuple(claims.get("capabilities"))
        if not tenant_scope or not capabilities:
            raise M2MApiError(403, "M2M_FORBIDDEN", "Credencial M2M sem contexto autorizado.")

        now = datetime.now(timezone.utc).timestamp()
        try:
            issued_at = float(claims.get("iat"))
            expires_at = float(claims.get("exp"))
        except (TypeError, ValueError) as exc:
            raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Credencial M2M inválida.") from exc

        if (
            expires_at <= now
            or issued_at > now + 60
            or expires_at <= issued_at
            or expires_at - issued_at > self.settings.m2m_max_token_lifetime_seconds
        ):
            raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Credencial M2M inválida.")

        return M2MIdentity(
            subject=subject,
            client_id=client_id,
            credential_id=credential_id,
            issuer=issuer,
            source_environment=source_environment,
            tenant_scope=tenant_scope,
            capabilities=capabilities,
        )


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization") or ""
    if not authorization.startswith("Bearer "):
        raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Autenticação M2M necessária.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise M2MApiError(401, "M2M_UNAUTHENTICATED", "Autenticação M2M necessária.")
    return token


def require_m2m_capability(required_capability: str):
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ) -> M2MContext:
        request.state.m2m_requested_capability = required_capability
        ensure_request_ids(request)

        if not settings.m2m_enabled:
            raise M2MApiError(404, "M2M_FORBIDDEN", "Integração M2M indisponível.")

        if settings.m2m_auth_mode != "oidc_introspection":
            raise M2MApiError(503, "M2M_INTERNAL_ERROR", "Modo de autenticação M2M inválido.")

        validator = OidcIntrospectionM2MTokenValidator(settings)
        identity = validator.validate(_bearer_token(request))
        request.state.m2m_identity = identity

        context = M2MContextFactory().create(
            request=request,
            identity=identity,
            db=db,
            service_principal_id=settings.m2m_service_principal_id or "",
            requested_capability=required_capability,
        )

        if required_capability not in set(identity.capabilities):
            raise M2MApiError(
                403,
                "M2M_SCOPE_DENIED",
                "A identidade de serviço não possui a capability solicitada.",
            )
        return context

    return dependency
