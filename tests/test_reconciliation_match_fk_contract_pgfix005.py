from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Match
from tests.reconciliation_test_support import ensure_marketplace_match


def test_reconciliation_fixture_creates_real_marketplace_match(ids):
    with SessionLocal() as db:
        ensure_marketplace_match(db, ids, match_id="match-contract-1")
        db.commit()

    with SessionLocal() as db:
        match = db.scalar(
            select(Match).where(Match.match_id == "match-contract-1")
        )
        assert match is not None
        assert match.borrower_tenant_id == ids["client_tenant"]
        assert match.funder_tenant_id == ids["foreign_tenant"]
