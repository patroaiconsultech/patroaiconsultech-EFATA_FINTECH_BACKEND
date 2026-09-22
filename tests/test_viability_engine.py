from decimal import Decimal

import pytest

from app.viability_engine import calculate, sensitivity_matrix


@pytest.fixture
def base_inputs() -> dict:
    return {
        "base_date": "2026-01-15",
        "months": 6,
        "physical": {"units": 10, "area_equivalent_m2": 1000},
        "revenue": {
            "total_vgv": 1200000,
            "absorption_curve": [20, 20, 20, 20, 20, 0],
        },
        "costs": {
            "land_total": 200000,
            "construction_total": 700000,
            "other_total": 50000,
            "construction_curve": [10, 20, 25, 20, 15, 10],
        },
        "funding": {
            "construction_percent": 50,
            "annual_rate": 12,
            "grace_months": 2,
            "amortization_months": 4,
        },
        "discount": {"annual_rate": 18},
    }


def test_calculate_returns_monthly_flow_and_fcd_outputs(base_inputs: dict) -> None:
    result = calculate(base_inputs)

    assert result.outputs["engine_version"] == "m1-fcd-v1"
    assert len(result.flow) == 6
    assert result.outputs["total_vgv"] == 1_200_000.0
    assert result.outputs["construction_total"] == 700_000.0
    assert result.outputs["funding_cap"] == 350_000.0
    assert result.outputs["npv"] != 0
    assert result.flow[0]["period_start"] == "2026-01-01"
    assert "discount_factor" in result.flow[-1]


def test_calculate_does_not_hide_missing_inputs(base_inputs: dict) -> None:
    base_inputs["revenue"] = {}
    result = calculate(base_inputs)

    assert result.outputs["total_vgv"] == 0.0
    assert any("VGV" in warning for warning in result.warnings)


def test_sensitivity_matrix_changes_vgv(base_inputs: dict) -> None:
    results = sensitivity_matrix(base_inputs, "price", [Decimal("-0.10"), Decimal("0"), Decimal("0.10")])

    assert len(results) == 3
    assert results[0]["total_vgv"] < results[1]["total_vgv"] < results[2]["total_vgv"]


def test_invalid_horizon_is_rejected(base_inputs: dict) -> None:
    base_inputs["months"] = 0
    with pytest.raises(ValueError):
        calculate(base_inputs)
