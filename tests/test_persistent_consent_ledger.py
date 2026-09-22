from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ConsentLedgerEventRecord
from app.persistent_consent_ledger import PersistentConsentLedger, PersistentConsentViolation


def _issue(db, ids):
    now = datetime.now(timezone.utc)
    return PersistentConsentLedger().issue_grant(
        db,
        tenant_id=ids["client_tenant"],
        subject_ref="subject-hash-001",
        purpose="CREDIT_RISK_ANALYSIS",
        scopes=["transactions.read", "balances.read"],
        recipient="efata-risk-agent",
        source_institution="bank-adapter",
        granted_at=now,
        expires_at=now + timedelta(days=30),
        created_by=ids["client_user"],
        request_id="request-001",
        correlation_id="correlation-001",
    )


def test_issue_access_revoke_and_verify_chain(ids):
    service = PersistentConsentLedger()
    with SessionLocal() as db:
        grant = _issue(db, ids)
        db.commit()
        consent_id = grant.consent_id

        service.authorize_access(
            db,
            consent_id=consent_id,
            actor_id=ids["analyst_user"],
            purpose="CREDIT_RISK_ANALYSIS",
            scopes=["transactions.read"],
            request_id="request-002",
            correlation_id="correlation-002",
        )
        service.revoke_grant(
            db,
            consent_id=consent_id,
            actor_id=ids["client_user"],
            request_id="request-003",
            correlation_id="correlation-003",
            reason="titular_requested",
        )
        db.commit()

        report = service.verify_chain(db, tenant_id=ids["client_tenant"])
        assert report["valid"] is True
        assert report["event_count"] == 3
        assert report["last_sequence"] == 3

        with pytest.raises(PersistentConsentViolation):
            service.authorize_access(
                db,
                consent_id=consent_id,
                actor_id=ids["analyst_user"],
                purpose="CREDIT_RISK_ANALYSIS",
                scopes=["transactions.read"],
                request_id="request-004",
                correlation_id="correlation-004",
            )


def test_revoke_is_idempotent(ids):
    service = PersistentConsentLedger()
    with SessionLocal() as db:
        grant = _issue(db, ids)
        db.commit()
        service.revoke_grant(
            db,
            consent_id=grant.consent_id,
            actor_id=ids["client_user"],
            request_id="request-revoke-1",
            correlation_id="correlation-revoke-1",
        )
        service.revoke_grant(
            db,
            consent_id=grant.consent_id,
            actor_id=ids["client_user"],
            request_id="request-revoke-2",
            correlation_id="correlation-revoke-2",
        )
        db.commit()
        events = db.scalars(
            select(ConsentLedgerEventRecord).where(ConsentLedgerEventRecord.consent_id == grant.consent_id)
        ).all()
        assert len(events) == 2
        assert events[-1].event_type == "CONSENT_REVOKED"


def test_verify_chain_detects_payload_tampering(ids):
    service = PersistentConsentLedger()
    with SessionLocal() as db:
        grant = _issue(db, ids)
        db.commit()
        event = db.scalar(
            select(ConsentLedgerEventRecord).where(ConsentLedgerEventRecord.consent_id == grant.consent_id)
        )
        assert event is not None
        event.payload_json = {**event.payload_json, "tampered": True}
        db.commit()

        report = service.verify_chain(db, tenant_id=ids["client_tenant"])
        assert report["valid"] is False
        assert report["failed_event_id"] == event.event_id
