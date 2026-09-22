from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

ENGINE_VERSION = "m1-fcd-v1"
ZERO = Decimal("0")
CENT = Decimal("0.01")


def dec(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise ValueError(f"Valor monetário inválido: {value}") from exc


def money(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def pct(value: Any, default: Decimal = ZERO) -> Decimal:
    result = dec(value, default)
    return result / Decimal("100") if abs(result) > Decimal("1") else result


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def month_start(base_date: date, offset: int) -> date:
    index = (base_date.year * 12 + base_date.month - 1) + offset
    return date(index // 12, index % 12 + 1, 1)


def normalized_curve(values: list[Any] | None, months: int, *, default_months: int | None = None) -> list[Decimal]:
    if values:
        curve = [pct(value) for value in values]
        if len(curve) > months:
            curve = curve[:months]
        curve.extend([ZERO] * (months - len(curve)))
        total = sum(curve, ZERO)
        if total > ZERO:
            return [item / total for item in curve]
    active_months = max(1, min(months, default_months or months))
    curve = [Decimal("1") / Decimal(active_months) if index < active_months else ZERO for index in range(months)]
    return curve


def _schedule(total: Decimal, curve: list[Decimal]) -> list[Decimal]:
    return [total * item for item in curve]


def _annual_to_monthly(rate: Decimal) -> Decimal:
    if rate <= Decimal("-1"):
        raise ValueError("A taxa anual deve ser maior que -100%.")
    return (Decimal("1") + rate) ** (Decimal("1") / Decimal("12")) - Decimal("1")


@dataclass(frozen=True)
class CalculationResult:
    outputs: dict[str, Any]
    flow: list[dict[str, Any]]
    warnings: list[str]


def calculate(inputs: dict[str, Any], overrides: dict[str, Any] | None = None) -> CalculationResult:
    data = deep_merge(inputs, overrides or {})
    warnings: list[str] = []

    base_date_raw = data.get("base_date") or date.today().isoformat()
    base_date = date.fromisoformat(str(base_date_raw)[:10])
    months_value = data.get("months")
    if months_value is None:
        months_value = data.get("timeline", {}).get("months")
    if months_value is None:
        months_value = 24
    months = int(months_value)
    if months < 1 or months > 240:
        raise ValueError("O horizonte mensal deve estar entre 1 e 240 meses.")

    physical = data.get("physical", {})
    revenue = data.get("revenue", {})
    costs = data.get("costs", {})
    funding = data.get("funding", {})
    discount = data.get("discount", {})

    units = int(physical.get("units") or 0)
    area_equivalent = dec(physical.get("area_equivalent_m2"))
    if units <= 0:
        warnings.append("Número de unidades ausente ou não positivo.")
    if area_equivalent <= ZERO:
        warnings.append("Área equivalente ausente; custo por área não será validado.")

    total_vgv = dec(revenue.get("total_vgv"))
    if total_vgv <= ZERO:
        quantity = dec(revenue.get("units"), Decimal(units))
        unit_price = dec(revenue.get("average_unit_price"))
        total_vgv = quantity * unit_price
    if total_vgv <= ZERO:
        warnings.append("VGV total ausente ou não positivo.")

    absorption = normalized_curve(
        revenue.get("absorption_curve"),
        months,
        default_months=int(revenue.get("absorption_months") or min(months, 12)),
    )
    revenue_schedule = revenue.get("cash_schedule")
    if revenue_schedule:
        revenue_values = [dec(item) for item in revenue_schedule[:months]]
        revenue_values.extend([ZERO] * (months - len(revenue_values)))
    else:
        revenue_values = _schedule(total_vgv, absorption)

    land_total = dec(costs.get("land_total"))
    construction_total = dec(costs.get("construction_total"))
    other_total = dec(costs.get("other_total"))
    if construction_total <= ZERO and area_equivalent > ZERO:
        cost_per_m2 = dec(costs.get("construction_cost_per_equivalent_m2"))
        bdi = pct(costs.get("bdi"))
        uplifts = pct(costs.get("uplifts"))
        construction_total = area_equivalent * cost_per_m2 * (Decimal("1") + bdi + uplifts)
    if construction_total <= ZERO:
        warnings.append("Custo total de construção ausente ou não positivo.")

    land_schedule = costs.get("land_schedule")
    if land_schedule:
        land_values = [dec(item) for item in land_schedule[:months]]
        land_values.extend([ZERO] * (months - len(land_values)))
    else:
        land_values = [land_total] + [ZERO] * (months - 1)

    construction_curve = normalized_curve(
        costs.get("construction_curve"),
        months,
        default_months=int(costs.get("construction_months") or min(months, 24)),
    )
    construction_values = _schedule(construction_total, construction_curve)

    other_curve = normalized_curve(costs.get("other_curve"), months, default_months=months)
    other_values = _schedule(other_total, other_curve)

    funding_pct = pct(funding.get("construction_percent"))
    funding_pct = max(ZERO, min(Decimal("1"), funding_pct))
    funding_cap = construction_total * funding_pct
    funding_draw_values = []
    remaining_funding = funding_cap
    for cost_value in construction_values:
        draw = min(cost_value * funding_pct, remaining_funding)
        funding_draw_values.append(draw)
        remaining_funding -= draw

    annual_funding_rate = pct(funding.get("annual_rate"))
    monthly_funding_rate = _annual_to_monthly(annual_funding_rate)
    annual_discount_rate = pct(discount.get("annual_rate"))
    monthly_discount_rate = _annual_to_monthly(annual_discount_rate)
    grace_months = max(0, int(funding.get("grace_months") or 0))
    amortization_months = max(0, int(funding.get("amortization_months") or 0))

    equity_schedule = funding.get("equity_schedule")
    if equity_schedule:
        equity_values = [dec(item) for item in equity_schedule[:months]]
        equity_values.extend([ZERO] * (months - len(equity_values)))
    else:
        equity_values = [ZERO] * months

    debt = ZERO
    cumulative = ZERO
    cumulative_unlevered = ZERO
    cumulative_present_value = ZERO
    cumulative_unlevered_present_value = ZERO
    flow: list[dict[str, Any]] = []
    total_interest = ZERO
    total_principal = ZERO
    min_pre_equity_cumulative = ZERO
    min_project_cumulative = ZERO

    for index in range(months):
        interest = debt * monthly_funding_rate
        principal = ZERO
        if amortization_months and index >= grace_months and debt > ZERO:
            principal = min(funding_cap / Decimal(amortization_months), debt)
        debt = max(ZERO, debt + funding_draw_values[index] - principal)
        project_cash_flow = revenue_values[index] - land_values[index] - construction_values[index] - other_values[index]
        pre_equity_cash_flow = project_cash_flow + funding_draw_values[index] - interest - principal
        net_cash_flow = pre_equity_cash_flow + equity_values[index]
        cumulative += net_cash_flow
        cumulative_unlevered += project_cash_flow
        min_pre_equity_cumulative = min(min_pre_equity_cumulative, cumulative - sum(equity_values[: index + 1], ZERO))
        min_project_cumulative = min(min_project_cumulative, cumulative_unlevered)
        discount_factor = Decimal("1") / ((Decimal("1") + monthly_discount_rate) ** Decimal(index))
        present_value = net_cash_flow * discount_factor
        unlevered_present_value = project_cash_flow * discount_factor
        cumulative_present_value += present_value
        cumulative_unlevered_present_value += unlevered_present_value
        total_interest += interest
        total_principal += principal
        flow.append(
            {
                "period_start": month_start(base_date, index).isoformat(),
                "revenue": money(revenue_values[index]),
                "equity_contribution": money(equity_values[index]),
                "funding_draw": money(funding_draw_values[index]),
                "land_cost": money(land_values[index]),
                "construction_cost": money(construction_values[index]),
                "other_costs": money(other_values[index]),
                "interest": money(interest),
                "principal": money(principal),
                "project_cash_flow": money(project_cash_flow),
                "net_cash_flow": money(net_cash_flow),
                "cumulative_cash_flow": money(cumulative),
                "debt_balance": money(debt),
                "discount_factor": float(discount_factor),
                "present_value": money(present_value),
                "unlevered_present_value": money(unlevered_present_value),
            }
        )

    required_equity = max(ZERO, -min_pre_equity_cumulative)
    unlevered_required_equity = max(ZERO, -min_project_cumulative)
    payback_month = next((row["period_start"] for row in flow if row["cumulative_cash_flow"] >= 0), None)
    discounted_payback_month = next(
        (
            row["period_start"]
            for row in flow
            if sum(dec(item["present_value"]) for item in flow[: flow.index(row) + 1]) >= ZERO
        ),
        None,
    )

    outputs = {
        "engine_version": ENGINE_VERSION,
        "months": months,
        "base_date": base_date.isoformat(),
        "total_vgv": money(total_vgv),
        "land_total": money(sum(land_values, ZERO)),
        "construction_total": money(construction_total),
        "other_total": money(other_total),
        "funding_cap": money(funding_cap),
        "required_equity": money(required_equity),
        "unlevered_required_equity": money(unlevered_required_equity),
        "total_interest": money(total_interest),
        "total_principal": money(total_principal),
        "npv": money(cumulative_present_value),
        "unlevered_npv": money(cumulative_unlevered_present_value),
        "payback_month": payback_month,
        "discounted_payback_month": discounted_payback_month,
        "discount_rate_annual": float(annual_discount_rate),
        "funding_rate_annual": float(annual_funding_rate),
        "min_cumulative_cash_flow": money(min((dec(row["cumulative_cash_flow"]) for row in flow), default=ZERO)),
    }
    if monthly_discount_rate == ZERO:
        warnings.append("Taxa de desconto igual a zero; o VPL coincide com a soma nominal do fluxo.")
    if sum(abs(item) for item in absorption) < Decimal("0.999"):
        warnings.append("A curva de absorção foi normalizada; confirme o estoque residual do cenário.")
    if annual_discount_rate < ZERO:
        warnings.append("Taxa de desconto negativa; revisar convenção financeira.")
    return CalculationResult(outputs=outputs, flow=flow, warnings=warnings)


def sensitivity_matrix(inputs: dict[str, Any], variable: str, shocks: list[Decimal]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for shock in shocks:
        override: dict[str, Any]
        if variable == "price":
            override = {"revenue": {"total_vgv": money(dec(inputs.get("revenue", {}).get("total_vgv")) * (Decimal("1") + shock))}}
        elif variable == "construction_cost":
            override = {
                "costs": {
                    "construction_total": money(dec(inputs.get("costs", {}).get("construction_total")) * (Decimal("1") + shock))
                }
            }
        elif variable == "funding_rate":
            override = {"funding": {"annual_rate": money((pct(inputs.get("funding", {}).get("annual_rate")) * (Decimal("1") + shock)) * Decimal("100"))}}
        elif variable == "delay_months":
            delay = max(0, int(shock))
            existing = inputs.get("costs", {}).get("construction_curve", [])
            override = {"costs": {"construction_curve": [0] * delay + list(existing)}}
        elif variable == "absorption":
            curve = inputs.get("revenue", {}).get("absorption_curve", [])
            override = {"revenue": {"absorption_curve": [dec(value) * (Decimal("1") + shock) for value in curve]}}
        else:
            raise ValueError(f"Variável de sensibilidade não suportada: {variable}")
        calculated = calculate(inputs, override)
        results.append({"variable": variable, "shock": float(shock), **calculated.outputs, "warnings": calculated.warnings})
    return results
