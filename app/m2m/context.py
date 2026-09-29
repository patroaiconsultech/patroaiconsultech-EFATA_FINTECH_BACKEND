from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.m2m.errors import M2MApiError
from app.models import Tenant


TENANT_HEADER = "X-Tenant-ID"
ORGANIZATION_HEADER = "X-Organization-ID"
EXECUTION_HEADER = "X-Execution-ID"


def _uuid_text(value: str | None, *, field: str, required: bool = True) -> str | None:
    raw = (value or "").strip()
    if not raw:
        if required:
            raise M2MApiError(
                422,
                "M2M_VALIDATION_ERROR",
                f"{field} é obrigatório.",
                details=[{"field": field, "reason": "required"}],
            )
        return None
    try:
        return str(UUID(raw))
    except ValueError as exc:
        raise M2MApiError(
            422,
            "M2M_VALIDATION_ERROR",
            f"{field} deve ser UUID.",
            details=[{"field": field, "reason": "invalid_uuid"}],
        ) from exc


def ensure_request_ids(request: Request) -> tuple[str, str, str]:
    # Audit persistence stores request/correlation IDs in VARCHAR(36), so M2M
    # accepts only UUIDs at this boundary. Even an invalid caller-provided ID
    # receives fresh safe IDs for observability of the rejection itself.
    execution_id = _uuid_text(
        request.headers.get(EXECUTION_HEADER) or str(uuid4()),
        field="execution_id",
    )
    request.state.m2m_execution_id = execution_id

    raw_request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or str(uuid4())
    )
    try:
        request_id = _uuid_text(raw_request_id, field="request_id")
    except M2MApiError:
        safe_id = str(uuid4())
        request.state.request_id = safe_id
        request.state.correlation_id = safe_id
        raise

    raw_correlation_id = (
        getattr(request.state, "correlation_id", None)
        or request.headers.get("X-Correlation-ID")
        or request_id
    )
    try:
        correlation_id = _uuid_text(raw_correlation_id, field="correlation_id")
    except M2MApiError:
        request.state.request_id = request_id
        request.state.correlation_id = request_id
        raise

    request.state.request_id = request_id
    request.state.correlation_id = correlation_id
    return request_id, correlation_id, execution_id


@dataclass(frozen=True)
class M2MIdentity:
    subject: str
    client_id: str
    credential_id: str
    issuer: str
    source_environment: str
    tenant_scope: tuple[str, ...]
    capabilities: tuple[str, ...]
    provider: str = "oidc_introspection"


@dataclass(frozen=True)
class M2MContext:
    service_principal_id: str
    service_subject: str
    client_id: str
    credential_id: str
    tenant_id: str
    organization_id: str
    request_id: str
    execution_id: str
    correlation_id: str
    source_platform: str
    source_environment: str
    requested_capability: str
    governance_mode: str = "controlled"
    write_allowed: bool = False
    execution_allowed: bool = False
    data_classification: str = "INTERNAL"


class M2MContextFactory:
    def create(
        self,
        *,
        request: Request,
        identity: M2MIdentity,
        db: Session,
        service_principal_id: str,
        requested_capability: str,
    ) -> M2MContext:
        request_id, correlation_id, execution_id = ensure_request_ids(request)

        tenant_id = _uuid_text(
            request.headers.get(TENANT_HEADER),
            field="tenant_id",
        )
        organization_id = _uuid_text(
            request.headers.get(ORGANIZATION_HEADER),
            field="organization_id",
        )
        service_principal_id = _uuid_text(
            service_principal_id,
            field="service_principal_id",
        )

        if tenant_id not in set(identity.tenant_scope):
            raise M2MApiError(
                403,
                "M2M_TENANT_DENIED",
                "O tenant solicitado não está autorizado para esta identidade de serviço.",
            )

        tenant = db.scalar(
            select(Tenant).where(
                Tenant.tenant_id == tenant_id,
                Tenant.status == "ACTIVE",
            )
        )
        if tenant is None or tenant.organization_id != organization_id:
            # Fail closed and do not disclose whether the tenant or organization exists.
            raise M2MApiError(
                403,
                "M2M_TENANT_DENIED",
                "O tenant solicitado não está autorizado para esta identidade de serviço.",
            )

        context = M2MContext(
            service_principal_id=service_principal_id,
            service_subject=identity.subject,
            client_id=identity.client_id,
            credential_id=identity.credential_id,
            tenant_id=tenant.tenant_id,
            organization_id=tenant.organization_id,
            request_id=request_id,
            execution_id=execution_id,
            correlation_id=correlation_id,
            source_platform=identity.issuer,
            source_environment=identity.source_environment,
            requested_capability=requested_capability,
        )
        request.state.m2m_context = context
        return context
