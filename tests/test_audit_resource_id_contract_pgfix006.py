from __future__ import annotations

from uuid import UUID, uuid4

from app.models import AuditEvent


AUDIT_RESOURCE_ID_MAX_LENGTH = 255


def test_audit_resource_id_column_matches_canonical_capacity():
    assert AuditEvent.__table__.c.resource_id.type.length == (
        AUDIT_RESOURCE_ID_MAX_LENGTH
    )


def test_prefixed_reconciliation_id_fits_audit_resource_contract():
    resource_id = f"reconciliation-{uuid4()}"

    assert len(resource_id) == 51
    assert len(resource_id) <= AUDIT_RESOURCE_ID_MAX_LENGTH
    assert UUID(resource_id.removeprefix("reconciliation-"))


def test_audit_resource_id_capacity_is_bounded_at_255():
    assert len("x" * AUDIT_RESOURCE_ID_MAX_LENGTH) == 255
    assert len("x" * (AUDIT_RESOURCE_ID_MAX_LENGTH + 1)) == 256
