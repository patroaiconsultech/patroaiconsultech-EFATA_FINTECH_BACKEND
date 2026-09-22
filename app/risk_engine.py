from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


POLICY_VERSION = "credit-risk-demo-v1"
REQUIRED_DOCUMENT_TYPES = {"FINANCIAL_STATEMENTS", "CORPORATE_DOCUMENTS"}


@dataclass(frozen=True)
class RiskRuleResult:
    rule_key: str
    label: str
    status: str
    value: Any
    threshold: Any
    source: str
    explanation: str
    score_contribution: int


@dataclass(frozen=True)
class RiskEvaluation:
    decision: str
    risk_band: str
    score: int
    recommendation: str
    rule_results: list[RiskRuleResult]
    evidence: list[dict[str, Any]]
    missing_data: list[str]
    hard_flags: list[str]
    soft_flags: list[str]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _rule(
    rule_key: str,
    label: str,
    status: str,
    value: Any,
    threshold: Any,
    source: str,
    explanation: str,
    score_contribution: int,
) -> RiskRuleResult:
    return RiskRuleResult(
        rule_key=rule_key,
        label=label,
        status=status,
        value=value,
        threshold=threshold,
        source=source,
        explanation=explanation,
        score_contribution=score_contribution,
    )


def evaluate_risk(payload: Any) -> RiskEvaluation:
    rules: list[RiskRuleResult] = []
    evidence: list[dict[str, Any]] = []
    missing_data: list[str] = []
    hard_flags: list[str] = []
    soft_flags: list[str] = []
    score = 0

    consent = getattr(payload, "consent_status", None)
    if consent == "GRANTED":
        rules.append(_rule("consent", "Consentimento e escopo", "PASS", consent, "GRANTED", "declared", "Consentimento concedido para avaliação e matching.", 10))
        score += 10
    else:
        hard_flags.append("CONSENT_REQUIRED")
        rules.append(_rule("consent", "Consentimento e escopo", "BLOCK", consent, "GRANTED", "declared", "A avaliação não pode avançar sem consentimento concedido.", 0))

    amount = _decimal(getattr(payload, "requested_amount", None))
    term = int(getattr(payload, "term_months", 0) or 0)
    currency = getattr(payload, "currency", "")
    purpose = str(getattr(payload, "purpose", "") or "").strip()
    stage = str(getattr(payload, "project_stage", "") or "").strip()
    operation_valid = bool(amount and amount > 0 and len(currency) == 3 and 1 <= term <= 600 and len(purpose) >= 3 and len(stage) >= 2)
    if operation_valid:
        rules.append(_rule("operation_coherence", "Validade da operação", "PASS", {"amount": str(amount), "currency": currency, "term_months": term}, "amount>0; term 1-600; context present", "declared", "Valor, prazo, moeda, finalidade e estágio estão preenchidos de forma coerente.", 15))
        score += 15
        evidence.append({"field": "operation", "value": {"amount": str(amount), "currency": currency, "term_months": term, "stage": stage}, "source": "declared"})
    else:
        hard_flags.append("INVALID_OPERATION_CONTEXT")
        rules.append(_rule("operation_coherence", "Validade da operação", "BLOCK", {"amount": str(amount) if amount is not None else None, "currency": currency, "term_months": term}, "amount>0; term 1-600; context present", "declared", "Dados mínimos da operação estão ausentes ou incoerentes.", 0))

    document_types = set(getattr(payload, "document_types", None) or [])
    missing_documents = sorted(REQUIRED_DOCUMENT_TYPES - document_types)
    if not missing_documents:
        rules.append(_rule("dossier_completeness", "Integridade do dossiê", "PASS", sorted(document_types), sorted(REQUIRED_DOCUMENT_TYPES), "document_inventory", "Documentos mínimos de demonstrações financeiras e societário estão informados.", 15))
        score += 15
    else:
        missing_data.extend([f"document:{item}" for item in missing_documents])
        rules.append(_rule("dossier_completeness", "Integridade do dossiê", "MISSING", sorted(document_types), sorted(REQUIRED_DOCUMENT_TYPES), "document_inventory", "O dossiê ainda não contém todos os documentos mínimos para revisão.", 0))
        soft_flags.append("DOCUMENTS_INCOMPLETE")

    dscr = _decimal(getattr(payload, "dscr", None))
    revenue_monthly = _decimal(getattr(payload, "revenue_monthly", None))
    debt_service_monthly = _decimal(getattr(payload, "debt_service_monthly", None))
    if dscr is None and revenue_monthly is not None and debt_service_monthly is not None and debt_service_monthly > 0:
        dscr = revenue_monthly / debt_service_monthly
        dscr_source = "derived:revenue_monthly/debt_service_monthly"
    else:
        dscr_source = "declared"
    if dscr is None:
        missing_data.append("dscr_or_debt_service")
        rules.append(_rule("capacity", "Capacidade de pagamento", "MISSING", None, ">=1.20x", dscr_source, "DSCR não informado e não foi possível derivá-lo com os dados disponíveis.", 0))
    elif dscr >= Decimal("1.20"):
        score += 20
        rules.append(_rule("capacity", "Capacidade de pagamento", "PASS", str(dscr.quantize(Decimal("0.01"))), ">=1.20x", dscr_source, "Cobertura de serviço da dívida acima do limite indicativo da política demo.", 20))
        evidence.append({"field": "dscr", "value": str(dscr), "source": dscr_source})
    elif dscr >= Decimal("1.00"):
        score += 10
        soft_flags.append("DSCR_BELOW_TARGET")
        rules.append(_rule("capacity", "Capacidade de pagamento", "ALERT", str(dscr.quantize(Decimal("0.01"))), ">=1.20x", dscr_source, "Cobertura positiva, mas abaixo do alvo indicativo; requer mitigantes e revisão humana.", 10))
    else:
        soft_flags.append("DSCR_LOW")
        rules.append(_rule("capacity", "Capacidade de pagamento", "ALERT", str(dscr.quantize(Decimal("0.01"))), ">=1.20x", dscr_source, "Cobertura abaixo de 1,00x; escalar para análise de crédito e mitigantes.", 0))

    total_debt = _decimal(getattr(payload, "total_debt", None))
    ebitda_annual = _decimal(getattr(payload, "ebitda_annual", None))
    leverage = total_debt / ebitda_annual if total_debt is not None and ebitda_annual is not None and ebitda_annual > 0 else None
    if leverage is None:
        missing_data.append("leverage_or_ebitda")
        rules.append(_rule("leverage", "Alavancagem", "MISSING", None, "<=5.0x", "declared", "Alavancagem não foi calculada por falta de dívida total e EBITDA anual válidos.", 0))
    elif leverage <= Decimal("5.0"):
        score += 15
        rules.append(_rule("leverage", "Alavancagem", "PASS", str(leverage.quantize(Decimal("0.01"))), "<=5.0x", "derived:total_debt/ebitda_annual", "Alavancagem dentro do limite indicativo da política demo.", 15))
        evidence.append({"field": "leverage", "value": str(leverage), "source": "derived:total_debt/ebitda_annual"})
    elif leverage <= Decimal("7.0"):
        score += 7
        soft_flags.append("LEVERAGE_ABOVE_TARGET")
        rules.append(_rule("leverage", "Alavancagem", "ALERT", str(leverage.quantize(Decimal("0.01"))), "<=5.0x", "derived:total_debt/ebitda_annual", "Alavancagem acima do alvo; requer estrutura e mitigantes.", 7))
    else:
        soft_flags.append("LEVERAGE_HIGH")
        rules.append(_rule("leverage", "Alavancagem", "ALERT", str(leverage.quantize(Decimal("0.01"))), "<=5.0x", "derived:total_debt/ebitda_annual", "Alavancagem elevada para a triagem; escalar para revisão humana.", 0))

    collateral_value = _decimal(getattr(payload, "collateral_value", None))
    ltv = _decimal(getattr(payload, "ltv", None))
    requested = amount or Decimal("0")
    if ltv is None and collateral_value is not None and collateral_value > 0:
        ltv = requested / collateral_value
        ltv_source = "derived:requested_amount/collateral_value"
    else:
        ltv_source = "declared"
    if ltv is None:
        missing_data.append("ltv_or_collateral_value")
        rules.append(_rule("collateral_coverage", "Garantia e cobertura", "MISSING", None, "<=75%", ltv_source, "LTV e valor de garantia não foram informados.", 0))
    elif ltv <= Decimal("0.75"):
        score += 15
        rules.append(_rule("collateral_coverage", "Garantia e cobertura", "PASS", f"{(ltv * 100).quantize(Decimal('0.1'))}%", "<=75%", ltv_source, "Cobertura dentro do limite indicativo da política demo.", 15))
        evidence.append({"field": "ltv", "value": str(ltv), "source": ltv_source})
    elif ltv <= Decimal("0.85"):
        score += 7
        soft_flags.append("LTV_ABOVE_TARGET")
        rules.append(_rule("collateral_coverage", "Garantia e cobertura", "ALERT", f"{(ltv * 100).quantize(Decimal('0.1'))}%", "<=75%", ltv_source, "LTV acima do alvo; exige análise de garantia e mitigantes.", 7))
    else:
        soft_flags.append("LTV_HIGH")
        rules.append(_rule("collateral_coverage", "Garantia e cobertura", "ALERT", f"{(ltv * 100).quantize(Decimal('0.1'))}%", "<=75%", ltv_source, "LTV elevado para a triagem; escalar para revisão humana.", 0))

    confidence = str(getattr(payload, "financial_data_confidence", "MISSING") or "MISSING").upper()
    confidence_scores = {"HIGH": 10, "MEDIUM": 6, "LOW": 2, "MISSING": 0}
    confidence_score = confidence_scores.get(confidence, 0)
    score += confidence_score
    if confidence == "MISSING":
        missing_data.append("financial_data_confidence")
    elif confidence in {"LOW", "MEDIUM"}:
        soft_flags.append("FINANCIAL_DATA_CONFIDENCE_LIMITED")
    rules.append(_rule("financial_quality", "Qualidade dos dados financeiros", "PASS" if confidence == "HIGH" else "ALERT" if confidence in {"LOW", "MEDIUM"} else "MISSING", confidence, "HIGH", "declared", "Nível de confiança declarado para os dados financeiros disponíveis.", confidence_score))

    score = max(0, min(100, score))
    if hard_flags:
        decision = "BLOCKED"
        risk_band = "UNDETERMINED"
        recommendation = "Não liberar o match; resolver os hard gates e registrar a evidência."
    elif missing_data:
        decision = "INFORMATION_REQUIRED"
        risk_band = "UNDETERMINED"
        recommendation = "Solicitar os dados e documentos ausentes antes da revisão do match."
    elif score >= 80:
        decision = "ELIGIBLE_FOR_REVIEW"
        risk_band = "LOW"
        recommendation = "Encaminhar para revisão humana de liberação do match."
    elif score >= 60:
        decision = "CONDITIONAL_REVIEW"
        risk_band = "MEDIUM"
        recommendation = "Revisar alertas, mitigantes e estrutura antes de decidir o próximo passo."
    else:
        decision = "CONDITIONAL_REVIEW"
        risk_band = "HIGH"
        recommendation = "Escalar para análise humana aprofundada; não liberar contato automaticamente."

    return RiskEvaluation(
        decision=decision,
        risk_band=risk_band,
        score=score,
        recommendation=recommendation,
        rule_results=rules,
        evidence=evidence,
        missing_data=sorted(set(missing_data)),
        hard_flags=sorted(set(hard_flags)),
        soft_flags=sorted(set(soft_flags)),
    )
