from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    BorrowerProfile,
    CreditRequest,
    FundingProduct,
    FundingProvider,
    Match,
)


def ensure_marketplace_match(
    db: Session,
    ids: dict[str, str],
    *,
    match_id: str,
) -> None:
    """Create the minimal valid marketplace graph required by commission FKs.

    Reconciliation persistence references marketplace_matches.match_id.
    PostgreSQL enforces that FK, so tests must persist a real Match rather than
    using a synthetic string that exists nowhere in the marketplace tables.
    """
    if db.get(Match, match_id) is not None:
        return

    borrower_profile_id = f"bp-{match_id}"
    funding_provider_id = f"fp-{match_id}"
    funding_product_id = f"product-{match_id}"
    credit_request_id = f"request-{match_id}"

    db.add(
        BorrowerProfile(
            borrower_profile_id=borrower_profile_id,
            tenant_id=ids["client_tenant"],
            segment="TEST",
            sectors=["TEST"],
            regions=["BR"],
            group_profile={},
            status="ACTIVE",
            created_by=ids["client_user"],
        )
    )
    db.flush()

    db.add(
        FundingProvider(
            funding_provider_id=funding_provider_id,
            tenant_id=ids["foreign_tenant"],
            provider_type="FUND",
            legal_name="PostgreSQL Reconciliation Test Funder",
            mandate_summary="Synthetic mandate used only by reconciliation tests.",
            status="ACTIVE",
            created_by=ids["foreign_user"],
        )
    )
    db.flush()

    db.add(
        FundingProduct(
            funding_product_id=funding_product_id,
            funding_provider_id=funding_provider_id,
            provider_tenant_id=ids["foreign_tenant"],
            name="Synthetic PostgreSQL Test Product",
            product_type="STRUCTURED_CREDIT",
            min_ticket=1,
            max_ticket=10000000,
            min_term_months=1,
            max_term_months=240,
            allowed_collateral_types=[],
            sectors=["TEST"],
            regions=["BR"],
            stage_requirements=[],
            indicative_terms={},
            currency="BRL",
            status="ACTIVE",
            created_by=ids["foreign_user"],
        )
    )
    db.flush()

    db.add(
        CreditRequest(
            credit_request_id=credit_request_id,
            owner_tenant_id=ids["client_tenant"],
            borrower_profile_id=borrower_profile_id,
            source_partner_tenant_id=None,
            title="Synthetic reconciliation request",
            credit_type="STRUCTURED_CREDIT",
            requested_amount=5000000,
            currency="BRL",
            term_months=24,
            grace_months=0,
            collateral_types=[],
            sectors=["TEST"],
            regions=["BR"],
            project_stage="TEST",
            purpose="PostgreSQL reconciliation fixture",
            consent_status="GRANTED",
            status="ACTIVE",
            version=1,
            created_by=ids["client_user"],
        )
    )
    db.flush()

    db.add(
        Match(
            match_id=match_id,
            credit_request_id=credit_request_id,
            funding_product_id=funding_product_id,
            borrower_tenant_id=ids["client_tenant"],
            funder_tenant_id=ids["foreign_tenant"],
            score=100,
            eligible=True,
            reasons=["TEST_FIXTURE"],
            gaps=[],
            status="SUGGESTED",
            assigned_agent_id=None,
            created_by=ids["analyst_user"],
        )
    )
    db.flush()
