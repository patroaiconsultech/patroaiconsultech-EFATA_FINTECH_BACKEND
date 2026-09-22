"""PostgreSQL-backed append-only Consent Ledger.

The application user must have INSERT/SELECT privileges on ledger events but no
UPDATE/DELETE privileges in production. A database role, trigger or archive
policy should enforce this boundary outside the ORM as well.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConsentGrantRecord, ConsentLedgerEventRecord, ConsentLedgerHeadRecord

GENESIS_HASH = "GENESIS"


class PersistentConsentViolation(ValueError):
    """Raised when a consent cannot authorize the requested access."""


class PersistentConsentLedger:
    """Append-only consent grants and access events in a SQL transaction."""

    def issue_grant(
        self,
        db: Session,
        *,
        tenant_id: str,
        subject_ref: str,
        purpose: str,
        scopes: Iterable[str],
        recipient: str,
        source_institution: str,
        granted_at: datetime,
        expires_at: datetime,
        created_by: str,
        provider_reference: str | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConsentGrantRecord:
        normalized_scopes = sorted({scope.strip() for scope in scopes if scope.strip()})
        if not normalized_scopes:
            raise ValueError("at least one scope is required")
        if expires_at <= granted_at:
            raise ValueError("expires_at must be after granted_at")
        grant = ConsentGrantRecord(
            consent_id=str(uuid4()),
            tenant_id=tenant_id,
            subject_ref=subject_ref,
            purpose=purpose,
            scopes=normalized_scopes,
            recipient=recipient,
            source_institution=source_institution,
            provider_reference=provider_reference,
            granted_at=granted_at,
            expires_at=expires_at,
            status="ACTIVE",
            metadata_json=metadata or {},
            created_by=created_by,
            created_at=granted_at,
        )
        db.add(grant)
        db.flush()
        self._append_event(
            db,
            tenant_id=tenant_id,
            consent_id=grant.consent_id,
            event_type="CONSENT_GRANTED",
            actor_id=created_by,
            purpose=purpose,
            scopes=normalized_scopes,
            payload={
                "consent_id": grant.consent_id,
                "subject_ref": subject_ref,
                "recipient": recipient,
                "source_institution": source_institution,
                "provider_reference": provider_reference,
                "granted_at": granted_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "metadata": metadata or {},
            },
            request_id=request_id or str(uuid4()),
            correlation_id=correlation_id or str(uuid4()),
            occurred_at=granted_at,
        )
        return grant

    def revoke_grant(
        self,
        db: Session,
        *,
        consent_id: str,
        actor_id: str,
        request_id: str,
        correlation_id: str,
        revoked_at: datetime | None = None,
        reason: str | None = None,
    ) -> ConsentGrantRecord:
        now = revoked_at or datetime.now(timezone.utc)
        grant = db.scalar(
            select(ConsentGrantRecord)
            .where(ConsentGrantRecord.consent_id == consent_id)
            .with_for_update()
        )
        if grant is None:
            raise KeyError(consent_id)
        if grant.status == "REVOKED":
            return grant
        grant.status = "REVOKED"
        grant.revoked_at = now
        db.flush()
        self._append_event(
            db,
            tenant_id=grant.tenant_id,
            consent_id=grant.consent_id,
            event_type="CONSENT_REVOKED",
            actor_id=actor_id,
            purpose=grant.purpose,
            scopes=grant.scopes,
            payload={"consent_id": consent_id, "reason": reason},
            request_id=request_id,
            correlation_id=correlation_id,
            occurred_at=now,
        )
        return grant

    def authorize_access(
        self,
        db: Session,
        *,
        consent_id: str,
        actor_id: str,
        purpose: str,
        scopes: Iterable[str],
        request_id: str,
        correlation_id: str,
        accessed_at: datetime | None = None,
        provider_reference: str | None = None,
    ) -> ConsentGrantRecord:
        now = accessed_at or datetime.now(timezone.utc)
        requested_scopes = sorted({scope.strip() for scope in scopes if scope.strip()})
        grant = db.scalar(
            select(ConsentGrantRecord)
            .where(ConsentGrantRecord.consent_id == consent_id)
            .with_for_update()
        )
        if grant is None:
            raise KeyError(consent_id)
        if (
            grant.status != "ACTIVE"
            or self._as_utc(grant.expires_at) <= self._as_utc(now)
            or grant.purpose != purpose
            or not set(requested_scopes).issubset(set(grant.scopes))
            or (provider_reference is not None and grant.provider_reference not in {None, provider_reference})
        ):
            raise PersistentConsentViolation(
                "consent is revoked, expired, outside purpose, missing scope, or bound to another provider"
            )
        self._append_event(
            db,
            tenant_id=grant.tenant_id,
            consent_id=grant.consent_id,
            event_type="DATA_ACCESS_ALLOWED",
            actor_id=actor_id,
            purpose=purpose,
            scopes=requested_scopes,
            payload={"consent_id": consent_id, "provider_reference": provider_reference},
            request_id=request_id,
            correlation_id=correlation_id,
            occurred_at=now,
        )
        return grant

    def append_audit_event(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        request_id: str,
        correlation_id: str,
        detail: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> ConsentLedgerEventRecord:
        occurred_at = occurred_at or datetime.now(timezone.utc)
        return self._append_event(
            db,
            tenant_id=tenant_id,
            consent_id=None,
            event_type=f"AUDIT_{action}",
            actor_id=actor_id,
            purpose="PLATFORM_AUDIT",
            scopes=[],
            payload={
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "detail": detail or {},
            },
            request_id=request_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )

    def verify_chain(self, db: Session, *, tenant_id: str) -> dict[str, Any]:
        events = db.scalars(
            select(ConsentLedgerEventRecord)
            .where(ConsentLedgerEventRecord.tenant_id == tenant_id)
            .order_by(ConsentLedgerEventRecord.sequence_no.asc())
        ).all()
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        for event in events:
            if event.sequence_no != expected_sequence or event.previous_hash != previous_hash:
                return {
                    "valid": False,
                    "tenant_id": tenant_id,
                    "failed_event_id": event.event_id,
                    "expected_sequence": expected_sequence,
                    "actual_sequence": event.sequence_no,
                }
            payload_hash = self._hash_payload(event.payload_json)
            event_hash = self._hash_event(
                sequence_no=event.sequence_no,
                event_type=event.event_type,
                actor_id=event.actor_id,
                purpose=event.purpose,
                scopes=event.scopes,
                request_id=event.request_id,
                correlation_id=event.correlation_id,
                payload_hash=payload_hash,
                previous_hash=previous_hash,
                occurred_at=event.occurred_at,
            )
            if event.payload_hash != payload_hash or event.event_hash != event_hash:
                return {"valid": False, "tenant_id": tenant_id, "failed_event_id": event.event_id}
            previous_hash = event_hash
            expected_sequence += 1
        head = db.scalar(
            select(ConsentLedgerHeadRecord).where(ConsentLedgerHeadRecord.tenant_id == tenant_id)
        )
        return {
            "valid": head is None or (head.last_sequence == len(events) and head.last_hash == previous_hash),
            "tenant_id": tenant_id,
            "event_count": len(events),
            "last_sequence": len(events),
            "last_hash": previous_hash,
        }

    def _append_event(
        self,
        db: Session,
        *,
        tenant_id: str,
        consent_id: str | None,
        event_type: str,
        actor_id: str,
        purpose: str,
        scopes: Iterable[str],
        payload: dict[str, Any],
        request_id: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> ConsentLedgerEventRecord:
        head = db.scalar(
            select(ConsentLedgerHeadRecord)
            .where(ConsentLedgerHeadRecord.tenant_id == tenant_id)
            .with_for_update()
        )
        if head is None:
            head = ConsentLedgerHeadRecord(
                tenant_id=tenant_id,
                last_sequence=0,
                last_hash=GENESIS_HASH,
                updated_at=occurred_at,
            )
            db.add(head)
            db.flush()
        sequence_no = head.last_sequence + 1
        normalized_scopes = sorted(set(scopes))
        payload_hash = self._hash_payload(payload)
        event_hash = self._hash_event(
            sequence_no=sequence_no,
            event_type=event_type,
            actor_id=actor_id,
            purpose=purpose,
            scopes=normalized_scopes,
            request_id=request_id,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            previous_hash=head.last_hash,
            occurred_at=occurred_at,
        )
        event = ConsentLedgerEventRecord(
            event_id=str(uuid4()),
            tenant_id=tenant_id,
            consent_id=consent_id,
            sequence_no=sequence_no,
            event_type=event_type,
            actor_id=actor_id,
            purpose=purpose,
            scopes=normalized_scopes,
            request_id=request_id,
            correlation_id=correlation_id,
            payload_json=payload,
            payload_hash=payload_hash,
            previous_hash=head.last_hash,
            event_hash=event_hash,
            occurred_at=occurred_at,
        )
        db.add(event)
        head.last_sequence = sequence_no
        head.last_hash = event_hash
        head.updated_at = occurred_at
        db.flush()
        return event

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _canonical_datetime(value: datetime) -> str:
        return PersistentConsentLedger._as_utc(value).isoformat()

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_event(
        *,
        sequence_no: int,
        event_type: str,
        actor_id: str,
        purpose: str,
        scopes: Iterable[str],
        request_id: str,
        correlation_id: str,
        payload_hash: str,
        previous_hash: str,
        occurred_at: datetime,
    ) -> str:
        canonical = json.dumps(
            {
                "sequence_no": sequence_no,
                "event_type": event_type,
                "actor_id": actor_id,
                "purpose": purpose,
                "scopes": sorted(scopes),
                "request_id": request_id,
                "correlation_id": correlation_id,
                "payload_hash": payload_hash,
                "previous_hash": previous_hash,
                "occurred_at": PersistentConsentLedger._canonical_datetime(occurred_at),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
