from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.persistent_consent_ledger import PersistentConsentLedger
from app.security import SecurityContext


_persistent_ledger = PersistentConsentLedger()


def record_audit(
    db: Session,
    *,
    context: SecurityContext,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: str,
    correlation_id: str,
    tenant_id: str | None = None,
    detail: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id or context.tenant_id,
        actor_id=context.user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        correlation_id=correlation_id,
        detail=detail or {},
    )
    db.add(event)
    _persistent_ledger.append_audit_event(
        db,
        tenant_id=event.tenant_id,
        actor_id=event.actor_id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        request_id=event.request_id,
        correlation_id=event.correlation_id,
        detail=event.detail,
        occurred_at=datetime.now(timezone.utc),
    )
    return event
