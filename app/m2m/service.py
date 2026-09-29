from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.m2m.errors import M2MApiError
from app.m2m.scopes import M2M_API_VERSION, M2M_CONTRACT_VERSION, R1_CAPABILITIES
from app.models import AuditEvent


def _encode_cursor(event: AuditEvent) -> str:
    payload = json.dumps(
        {
            "occurred_at": event.occurred_at.isoformat(),
            "audit_event_id": event.audit_event_id,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        occurred_at = datetime.fromisoformat(str(data["occurred_at"]))
        audit_event_id = str(data["audit_event_id"])
        if not audit_event_id:
            raise ValueError("missing audit_event_id")
        return occurred_at, audit_event_id
    except Exception as exc:
        raise M2MApiError(
            422,
            "M2M_VALIDATION_ERROR",
            "Cursor de auditoria inválido.",
            details=[{"field": "cursor", "reason": "invalid_cursor"}],
        ) from exc


class M2MReadService:
    def health(self, db: Session, settings: Settings) -> dict[str, Any]:
        db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "service": settings.app_name,
            "environment": settings.app_env,
            "service_version": settings.release_version or "unknown",
            "release_sha": settings.release_sha or "unknown",
            "database": "reachable",
        }

    def runtime(self, db: Session, settings: Settings) -> dict[str, Any]:
        db.execute(text("SELECT 1"))
        return {
            "service": settings.app_name,
            "environment": settings.app_env,
            "api_version": M2M_API_VERSION,
            "contract_version": M2M_CONTRACT_VERSION,
            "service_version": settings.release_version or "unknown",
            "release_sha": settings.release_sha or "unknown",
            "feature_flags": {
                "m2m_enabled": settings.m2m_enabled,
                "premium_slice_enabled": settings.premium_slice_enabled,
            },
            "dependencies": {"database": "reachable"},
            "capabilities": [item.scope for item in R1_CAPABILITIES],
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "contract_version": M2M_CONTRACT_VERSION,
            "capabilities": [
                {
                    "scope": item.scope,
                    "method": item.method,
                    "path": item.path,
                    "nature": item.nature,
                    "tenant_required": item.tenant_required,
                    "write": item.write,
                }
                for item in R1_CAPABILITIES
            ],
        }

    def audit_events(
        self,
        db: Session,
        *,
        tenant_id: str,
        limit: int,
        cursor: str | None,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> tuple[list[AuditEvent], str | None]:
        if limit < 1 or limit > 100:
            raise M2MApiError(
                422,
                "M2M_VALIDATION_ERROR",
                "limit deve estar entre 1 e 100.",
                details=[{"field": "limit", "reason": "out_of_range"}],
            )
        if from_ts and to_ts and from_ts > to_ts:
            raise M2MApiError(
                422,
                "M2M_VALIDATION_ERROR",
                "Intervalo de auditoria inválido.",
                details=[{"field": "time_range", "reason": "from_after_to"}],
            )

        statement = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        if from_ts is not None:
            statement = statement.where(AuditEvent.occurred_at >= from_ts)
        if to_ts is not None:
            statement = statement.where(AuditEvent.occurred_at <= to_ts)

        if cursor:
            cursor_time, cursor_id = _decode_cursor(cursor)
            statement = statement.where(
                or_(
                    AuditEvent.occurred_at < cursor_time,
                    and_(
                        AuditEvent.occurred_at == cursor_time,
                        AuditEvent.audit_event_id < cursor_id,
                    ),
                )
            )

        events = db.scalars(
            statement
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.audit_event_id.desc())
            .limit(limit + 1)
        ).all()

        has_more = len(events) > limit
        page = list(events[:limit])
        next_cursor = _encode_cursor(page[-1]) if has_more and page else None
        return page, next_cursor
