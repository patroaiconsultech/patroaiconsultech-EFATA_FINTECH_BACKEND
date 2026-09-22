from dataclasses import dataclass
from decimal import Decimal

from app.models import CreditRequest, FundingProduct


@dataclass(frozen=True)
class MatchEvaluation:
    score: int
    eligible: bool
    reasons: list[str]
    gaps: list[str]


def _norm(value: str) -> str:
    return value.strip().casefold()


def _overlap(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return True
    normalized_left = {_norm(item) for item in left}
    return any(_norm(item) in normalized_left for item in right)


def evaluate_match(request: CreditRequest, product: FundingProduct) -> MatchEvaluation:
    score = 0
    reasons: list[str] = []
    gaps: list[str] = []

    if _norm(request.credit_type) == _norm(product.product_type) or _norm(product.product_type) == "all":
        score += 25
        reasons.append("modalidade compatível")
    else:
        gaps.append("modalidade fora do produto")

    amount = Decimal(str(request.requested_amount))
    if product.min_ticket <= amount <= product.max_ticket:
        score += 20
        reasons.append("ticket dentro da faixa")
    else:
        gaps.append("ticket fora da faixa")

    if product.min_term_months <= request.term_months <= product.max_term_months:
        score += 15
        reasons.append("prazo compatível")
    else:
        gaps.append("prazo fora da política")

    if _overlap(request.collateral_types, product.allowed_collateral_types):
        score += 15
        reasons.append("garantia potencialmente aderente")
    else:
        gaps.append("garantia não mapeada")

    if _overlap(request.sectors, product.sectors):
        score += 10
        reasons.append("setor coberto")
    else:
        gaps.append("setor fora do mandato")

    if _overlap(request.regions, product.regions):
        score += 10
        reasons.append("região coberta")
    else:
        gaps.append("região fora da cobertura")

    if not product.stage_requirements or _norm(request.project_stage) in {
        _norm(stage) for stage in product.stage_requirements
    }:
        score += 5
        reasons.append("estágio compatível")
    else:
        gaps.append("estágio não atende ao requisito")

    # This threshold prioritizes the internal queue; it does not approve credit.
    return MatchEvaluation(score=score, eligible=score >= 60, reasons=reasons, gaps=gaps)
