from sqlalchemy import select

import sys
from pathlib import Path

# Allow `python scripts/seed_demo.py` from the backend root, as documented.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base, SessionLocal, engine
from app.models import (
    BorrowerProfile,
    CreditRequest,
    FundingProduct,
    FundingProvider,
    Match,
    MatchEvent,
    RiskAssessment,
    Membership,
    Organization,
    PartnerProfile,
    Tenant,
    User,
)

ORIGINATOR_ORG = "10000000-0000-0000-0000-000000000001"
ORIGINATOR_TENANT = "00000000-0000-0000-0000-000000000001"
ORIGINATOR_USER = "20000000-0000-0000-0000-000000000001"

CLIENT_ORG = "10000000-0000-0000-0000-000000000002"
CLIENT_TENANT = "00000000-0000-0000-0000-000000000002"
CLIENT_USER = "20000000-0000-0000-0000-000000000002"

PLATFORM_ORG = "10000000-0000-0000-0000-000000000003"
PLATFORM_TENANT = "00000000-0000-0000-0000-000000000003"
ANALYST_USER = "20000000-0000-0000-0000-000000000003"

FUNDER_ORG = "10000000-0000-0000-0000-000000000004"
FUNDER_TENANT = "00000000-0000-0000-0000-000000000004"
FUNDER_USER = "20000000-0000-0000-0000-000000000004"
PARTNER_ORG = "10000000-0000-0000-0000-000000000005"
PARTNER_TENANT = "00000000-0000-0000-0000-000000000005"
PARTNER_USER = "20000000-0000-0000-0000-000000000005"
BORROWER_PROFILE_ID = "40000000-0000-0000-0000-000000000001"
FUNDING_PROVIDER_ID = "41000000-0000-0000-0000-000000000001"
FUNDING_PRODUCT_ID = "42000000-0000-0000-0000-000000000001"
PARTNER_PROFILE_ID = "43000000-0000-0000-0000-000000000001"
CREDIT_REQUEST_ID = "44000000-0000-0000-0000-000000000001"
MATCH_ID = "45000000-0000-0000-0000-000000000001"
RISK_ASSESSMENT_ID = "47000000-0000-0000-0000-000000000001"


def add_if_missing(db, model, pk_name: str, pk_value: str, **kwargs):
    if db.scalar(select(model).where(getattr(model, pk_name) == pk_value)) is None:
        db.add(model(**{pk_name: pk_value}, **kwargs))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        add_if_missing(db, Organization, "organization_id", ORIGINATOR_ORG,
                       legal_name="Originadora Demo", organization_type="ORIGINATOR")
        add_if_missing(db, Organization, "organization_id", CLIENT_ORG,
                       legal_name="Cliente Demo", organization_type="CAPITAL_SEEKER")
        add_if_missing(db, Organization, "organization_id", PLATFORM_ORG,
                       legal_name="Plataforma Demo", organization_type="PLATFORM_OPERATOR")
        add_if_missing(db, Organization, "organization_id", FUNDER_ORG,
                       legal_name="Fundo Horizonte Demo", organization_type="FUND")
        add_if_missing(db, Organization, "organization_id", PARTNER_ORG,
                       legal_name="Parceiro Origina Demo", organization_type="PARTNER")

        add_if_missing(db, Tenant, "tenant_id", ORIGINATOR_TENANT,
                       organization_id=ORIGINATOR_ORG, tenant_type="ORIGINATOR", slug="originator-demo")
        add_if_missing(db, Tenant, "tenant_id", CLIENT_TENANT,
                       organization_id=CLIENT_ORG, tenant_type="CAPITAL_SEEKER", slug="client-demo")
        add_if_missing(db, Tenant, "tenant_id", PLATFORM_TENANT,
                       organization_id=PLATFORM_ORG, tenant_type="PLATFORM_OPERATOR", slug="platform-demo")
        add_if_missing(db, Tenant, "tenant_id", FUNDER_TENANT,
                       organization_id=FUNDER_ORG, tenant_type="FUNDER", slug="funder-demo")
        add_if_missing(db, Tenant, "tenant_id", PARTNER_TENANT,
                       organization_id=PARTNER_ORG, tenant_type="PARTNER", slug="partner-demo")

        add_if_missing(db, User, "user_id", ORIGINATOR_USER,
                       email="originator@example.test", display_name="Originador Demo")
        add_if_missing(db, User, "user_id", CLIENT_USER,
                       email="client@example.test", display_name="Cliente Demo")
        add_if_missing(db, User, "user_id", ANALYST_USER,
                       email="analyst@example.test", display_name="Analista Demo")
        add_if_missing(db, User, "user_id", FUNDER_USER,
                       email="funder@example.test", display_name="Funder Demo")
        add_if_missing(db, User, "user_id", PARTNER_USER,
                       email="partner@example.test", display_name="Parceiro Demo")

        add_if_missing(db, Membership, "membership_id", "30000000-0000-0000-0000-000000000001",
                       user_id=ORIGINATOR_USER, tenant_id=ORIGINATOR_TENANT, role="ORIGINATOR_ADMIN")
        add_if_missing(db, Membership, "membership_id", "30000000-0000-0000-0000-000000000002",
                       user_id=CLIENT_USER, tenant_id=CLIENT_TENANT, role="CLIENT_ADMIN")
        add_if_missing(db, Membership, "membership_id", "30000000-0000-0000-0000-000000000003",
                       user_id=ANALYST_USER, tenant_id=PLATFORM_TENANT, role="ANALYST")
        add_if_missing(db, Membership, "membership_id", "30000000-0000-0000-0000-000000000004",
                       user_id=FUNDER_USER, tenant_id=FUNDER_TENANT, role="FUNDER_ADMIN")
        add_if_missing(db, Membership, "membership_id", "30000000-0000-0000-0000-000000000005",
                       user_id=PARTNER_USER, tenant_id=PARTNER_TENANT, role="PARTNER_ADMIN")

        add_if_missing(
            db,
            BorrowerProfile,
            "borrower_profile_id",
            BORROWER_PROFILE_ID,
            tenant_id=CLIENT_TENANT,
            segment="INCORPORADORA",
            sectors=["REAL_ESTATE"],
            regions=["SP"],
            group_profile={"stage": "STRUCTURED"},
            created_by=CLIENT_USER,
        )
        add_if_missing(
            db,
            FundingProvider,
            "funding_provider_id",
            FUNDING_PROVIDER_ID,
            tenant_id=FUNDER_TENANT,
            provider_type="FUND",
            legal_name="Fundo Horizonte Demo",
            website="https://example.test/fundo-horizonte",
            mandate_summary="Crédito estruturado para operações de real estate em São Paulo.",
            created_by=FUNDER_USER,
        )
        add_if_missing(
            db,
            FundingProduct,
            "funding_product_id",
            FUNDING_PRODUCT_ID,
            funding_provider_id=FUNDING_PROVIDER_ID,
            provider_tenant_id=FUNDER_TENANT,
            name="CRI Residencial SP",
            product_type="REAL_ESTATE",
            min_ticket=1000000,
            max_ticket=10000000,
            min_term_months=12,
            max_term_months=60,
            allowed_collateral_types=["RECEIVABLES"],
            sectors=["REAL_ESTATE"],
            regions=["SP"],
            stage_requirements=["STRUCTURED"],
            indicative_terms={"indexer": "IPCA", "rate_note": "indicativa"},
            currency="BRL",
            status="ACTIVE",
            created_by=FUNDER_USER,
        )
        add_if_missing(
            db,
            PartnerProfile,
            "partner_profile_id",
            PARTNER_PROFILE_ID,
            tenant_id=PARTNER_TENANT,
            partner_type="ADVISOR",
            focus_regions=["SP"],
            commercial_terms={"commission_model": "SUCCESS_FEE_PENDING_CONTRACT"},
            created_by=PARTNER_USER,
        )
        add_if_missing(
            db,
            CreditRequest,
            "credit_request_id",
            CREDIT_REQUEST_ID,
            owner_tenant_id=CLIENT_TENANT,
            borrower_profile_id=BORROWER_PROFILE_ID,
            source_partner_tenant_id=PARTNER_TENANT,
            title="Residencial Aurora Demo",
            credit_type="REAL_ESTATE",
            requested_amount=5000000,
            currency="BRL",
            term_months=36,
            grace_months=6,
            collateral_types=["RECEIVABLES"],
            sectors=["REAL_ESTATE"],
            regions=["SP"],
            project_stage="STRUCTURED",
            purpose="Financiamento da construção e comercialização do projeto demo.",
            consent_status="GRANTED",
            status="QUALIFIED",
            created_by=CLIENT_USER,
        )
        add_if_missing(
            db,
            Match,
            "match_id",
            MATCH_ID,
            credit_request_id=CREDIT_REQUEST_ID,
            funding_product_id=FUNDING_PRODUCT_ID,
            borrower_tenant_id=CLIENT_TENANT,
            funder_tenant_id=FUNDER_TENANT,
            score=100,
            eligible=True,
            reasons=["modalidade compatível", "ticket dentro da faixa", "prazo compatível", "garantia potencialmente aderente", "setor coberto", "região coberta", "estágio compatível"],
            gaps=[],
            status="AGENT_REVIEW",
            assigned_agent_id=ANALYST_USER,
            created_by=ANALYST_USER,
        )
        add_if_missing(
            db,
            MatchEvent,
            "match_event_id",
            "46000000-0000-0000-0000-000000000001",
            match_id=MATCH_ID,
            status="SUGGESTED",
            reason="Match demo calculado por regras R5.",
            actor_id=ANALYST_USER,
            visibility="INTERNAL",
        )
        add_if_missing(
            db,
            RiskAssessment,
            "assessment_id",
            RISK_ASSESSMENT_ID,
            credit_request_id=CREDIT_REQUEST_ID,
            policy_version="credit-risk-demo-v1",
            decision="ELIGIBLE_FOR_REVIEW",
            risk_band="LOW",
            score=100,
            recommendation="Encaminhar para revisão humana de liberação do match.",
            rule_results=[
                {"rule_key": "consent", "label": "Consentimento e escopo", "status": "PASS", "value": "GRANTED", "threshold": "GRANTED", "source": "declared", "explanation": "Consentimento concedido para avaliação e matching.", "score_contribution": 10},
                {"rule_key": "operation_coherence", "label": "Validade da operação", "status": "PASS", "value": {"amount": "5000000", "currency": "BRL", "term_months": 36}, "threshold": "amount>0; term 1-600; context present", "source": "declared", "explanation": "Valor, prazo, moeda, finalidade e estágio estão preenchidos de forma coerente.", "score_contribution": 15},
                {"rule_key": "dossier_completeness", "label": "Integridade do dossiê", "status": "PASS", "value": ["CORPORATE_DOCUMENTS", "FINANCIAL_STATEMENTS"], "threshold": ["CORPORATE_DOCUMENTS", "FINANCIAL_STATEMENTS"], "source": "document_inventory", "explanation": "Documentos mínimos de demonstrações financeiras e societário estão informados.", "score_contribution": 15},
                {"rule_key": "capacity", "label": "Capacidade de pagamento", "status": "PASS", "value": "2.00", "threshold": ">=1.20x", "source": "derived:revenue_monthly/debt_service_monthly", "explanation": "Cobertura de serviço da dívida acima do limite indicativo da política demo.", "score_contribution": 20},
                {"rule_key": "leverage", "label": "Alavancagem", "status": "PASS", "value": "2.67", "threshold": "<=5.0x", "source": "derived:total_debt/ebitda_annual", "explanation": "Alavancagem dentro do limite indicativo da política demo.", "score_contribution": 15},
                {"rule_key": "collateral_coverage", "label": "Garantia e cobertura", "status": "PASS", "value": "62.5%", "threshold": "<=75%", "source": "derived:requested_amount/collateral_value", "explanation": "Cobertura dentro do limite indicativo da política demo.", "score_contribution": 15},
                {"rule_key": "financial_quality", "label": "Qualidade dos dados financeiros", "status": "PASS", "value": "HIGH", "threshold": "HIGH", "source": "declared", "explanation": "Nível de confiança declarado para os dados financeiros disponíveis.", "score_contribution": 10},
            ],
            evidence=[
                {"field": "operation", "value": {"amount": "5000000", "currency": "BRL", "term_months": 36}, "source": "declared"},
                {"field": "dscr", "value": "2", "source": "derived:revenue_monthly/debt_service_monthly"},
                {"field": "leverage", "value": "2.6667", "source": "derived:total_debt/ebitda_annual"},
                {"field": "ltv", "value": "0.625", "source": "derived:requested_amount/collateral_value"},
            ],
            missing_data=[],
            hard_flags=[],
            soft_flags=[],
            human_status="PENDING",
            created_by=ANALYST_USER,
        )
        db.commit()
    print("Demo seed completed.")


if __name__ == "__main__":
    main()
