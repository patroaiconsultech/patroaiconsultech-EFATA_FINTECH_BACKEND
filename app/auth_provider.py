from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import Request

from app.config import Settings
from app.errors import ApiError


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    tenant_id: str
    asserted_roles: tuple[str, ...] = ()
    email: str | None = None
    external_subject: str | None = None
    provider: str = "unknown"


class JwtValidator(Protocol):
    def validate(self, token: str) -> AuthIdentity:
        ...


class OidcIntrospectionJwtValidator:
    def __init__(self, settings: Settings):
        self.settings = settings
        required = {
            "oidc_introspection_endpoint": settings.oidc_introspection_endpoint,
            "oidc_introspection_client_id": settings.oidc_introspection_client_id,
            "oidc_introspection_client_secret": settings.oidc_introspection_client_secret,
            "oidc_issuer": settings.oidc_issuer,
            "oidc_audience": settings.oidc_audience,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ApiError(
                503,
                "OIDC_CONFIGURATION_INCOMPLETE",
                "O provedor de identidade não está configurado.",
            )

    def validate(self, token: str) -> AuthIdentity:
        try:
            response = httpx.post(
                self.settings.oidc_introspection_endpoint,
                data={"token": token},
                auth=(
                    self.settings.oidc_introspection_client_id,
                    self.settings.oidc_introspection_client_secret,
                ),
                timeout=self.settings.oidc_http_timeout_seconds,
            )
            response.raise_for_status()
            claims: dict[str, Any] = response.json()
        except Exception as exc:
            raise ApiError(
                503,
                "IDENTITY_PROVIDER_UNAVAILABLE",
                "O provedor de identidade está indisponível.",
            ) from exc

        if not claims.get("active"):
            raise ApiError(401, "TOKEN_INACTIVE", "Credencial inválida.")

        if str(claims.get("iss") or "") != str(self.settings.oidc_issuer):
            raise ApiError(401, "TOKEN_ISSUER_INVALID", "Credencial inválida.")

        audience = claims.get("aud", [])
        audience = [audience] if isinstance(audience, str) else list(audience or [])
        if self.settings.oidc_audience not in audience:
            raise ApiError(401, "TOKEN_AUDIENCE_INVALID", "Credencial inválida.")

        user_id = str(claims.get(self.settings.oidc_user_claim) or "").strip()
        tenant_id = str(claims.get(self.settings.oidc_tenant_claim) or "").strip()
        if not user_id:
            raise ApiError(403, "OIDC_USER_CLAIM_MISSING", "Identidade não provisionada.")
        if not tenant_id:
            raise ApiError(403, "OIDC_TENANT_CLAIM_MISSING", "Identidade não provisionada.")

        raw_roles = claims.get(self.settings.oidc_roles_claim, [])
        if isinstance(raw_roles, str):
            asserted_roles = tuple(filter(None, (part.strip() for part in raw_roles.split(","))))
        else:
            asserted_roles = tuple(str(role) for role in (raw_roles or []))

        return AuthIdentity(
            user_id=user_id,
            tenant_id=tenant_id,
            asserted_roles=asserted_roles,
            email=claims.get("email"),
            external_subject=str(claims.get("sub") or "") or None,
            provider="oidc",
        )


class AuthProvider(Protocol):
    def authenticate(self, request: Request) -> AuthIdentity:
        ...


class MockAuthProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def authenticate(self, request: Request) -> AuthIdentity:
        if self.settings.app_env not in {"local", "test"}:
            raise ApiError(
                503,
                "MOCK_AUTH_DISABLED",
                "A autenticação de desenvolvimento está desabilitada neste ambiente.",
            )

        user_id = (request.headers.get("X-User-ID") or "").strip()
        tenant_id = (request.headers.get("X-Tenant-ID") or "").strip()
        if not user_id or not tenant_id:
            raise ApiError(401, "MOCK_IDENTITY_REQUIRED", "Autenticação necessária.")

        return AuthIdentity(
            user_id=user_id,
            tenant_id=tenant_id,
            provider="mock",
        )


class OidcProvider:
    def __init__(self, validator: JwtValidator):
        self.validator = validator

    def authenticate(self, request: Request) -> AuthIdentity:
        authorization = request.headers.get("Authorization") or ""
        if not authorization.startswith("Bearer "):
            raise ApiError(401, "BEARER_TOKEN_REQUIRED", "Autenticação necessária.")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise ApiError(401, "BEARER_TOKEN_REQUIRED", "Autenticação necessária.")
        return self.validator.validate(token)


def get_auth_provider(settings: Settings) -> AuthProvider:
    if settings.auth_provider == "mock":
        return MockAuthProvider(settings)
    if settings.auth_provider == "oidc":
        return OidcProvider(OidcIntrospectionJwtValidator(settings))
    raise ApiError(
        503,
        "AUTH_PROVIDER_NOT_SUPPORTED",
        "O provedor de identidade solicitado não está disponível.",
    )
