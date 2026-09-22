from decimal import Decimal

from app.risk_engine import evaluate_risk
from app.schemas import RiskSimulationInput


def base_payload(**overrides):
    payload = {
        "consent_status": "GRANTED",
        "requested_amount": Decimal("5000000"),
        "currency": "BRL",
        "term_months": 36,
        "project_stage": "STRUCTURED",
        "purpose": "Construção e comercialização do projeto.",
        "collateral_types": ["RECEIVABLES"],
        "sectors": ["REAL_ESTATE"],
        "regions": ["SP"],
        "document_types": ["FINANCIAL_STATEMENTS", "CORPORATE_DOCUMENTS"],
        "revenue_monthly": Decimal("1000000"),
        "debt_service_monthly": Decimal("500000"),
        "ebitda_annual": Decimal("1500000"),
        "total_debt": Decimal("4000000"),
        "collateral_value": Decimal("8000000"),
        "financial_data_confidence": "HIGH",
    }
    payload.update(overrides)
    return RiskSimulationInput(**payload)


def test_risk_matrix_returns_eligible_for_human_review():
    evaluation = evaluate_risk(base_payload())
    assert evaluation.decision == "ELIGIBLE_FOR_REVIEW"
    assert evaluation.risk_band == "LOW"
    assert evaluation.score == 100
    assert not evaluation.hard_flags
    assert evaluation.missing_data == []


def test_risk_matrix_blocks_without_consent():
    evaluation = evaluate_risk(base_payload(consent_status="PENDING"))
    assert evaluation.decision == "BLOCKED"
    assert "CONSENT_REQUIRED" in evaluation.hard_flags
    assert evaluation.risk_band == "UNDETERMINED"


def test_risk_matrix_requests_information_without_financial_evidence():
    evaluation = evaluate_risk(base_payload(document_types=[], financial_data_confidence="MISSING", revenue_monthly=None, debt_service_monthly=None, ebitda_annual=None, total_debt=None, collateral_value=None))
    assert evaluation.decision == "INFORMATION_REQUIRED"
    assert "document:CORPORATE_DOCUMENTS" in evaluation.missing_data
    assert "dscr_or_debt_service" in evaluation.missing_data
    assert "leverage_or_ebitda" in evaluation.missing_data


def test_risk_matrix_derives_conditional_band_from_alerts():
    evaluation = evaluate_risk(base_payload(dscr=Decimal("1.05"), ltv=Decimal("0.80"), financial_data_confidence="MEDIUM"))
    assert evaluation.decision == "CONDITIONAL_REVIEW"
    assert evaluation.risk_band == "MEDIUM"
    assert "DSCR_BELOW_TARGET" in evaluation.soft_flags
    assert "LTV_ABOVE_TARGET" in evaluation.soft_flags
