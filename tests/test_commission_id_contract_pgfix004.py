from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.post_closing import CommissionLedgerEntry


def test_estimated_commission_id_fits_persistent_schema_and_is_uuid():
    entry = CommissionLedgerEntry.estimate(
        match_id="match-1",
        beneficiary_tenant_id="00000000-0000-0000-0000-000000000003",
        trigger_event="CONTACT_RELEASED",
        base_amount=Decimal("5000000"),
        rate_bps=75,
        currency="BRL",
        contract_id="contract-a",
    )

    assert len(entry.commission_id) == 36
    assert str(UUID(entry.commission_id)) == entry.commission_id
