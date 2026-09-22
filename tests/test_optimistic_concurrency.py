from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import CapitalOpportunity, QualificationCase


def test_qualification_rejects_stale_version(client, ids, auth_headers):
    originator_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    client_headers = auth_headers(ids["client_user"], ids["client_tenant"])
    analyst_headers = auth_headers(ids["analyst_user"], ids["platform_tenant"])

    lead = client.post(
        "/api/v1/leads",
        headers=originator_headers,
        json={
            "prospective_client_name": "Empresa Concorrência",
            "opportunity_type": "STRUCTURED_CREDIT",
            "estimated_amount": "3000000.00",
            "currency": "BRL",
        },
    )
    representation = client.post(
        "/api/v1/representations",
        headers=originator_headers,
        json={
            "lead_id": lead.json()["lead_id"],
            "represented_tenant_id": ids["client_tenant"],
            "allowed_actions": ["CREATE_OPPORTUNITY", "VIEW_STATUS"],
        },
    )
    authorization_id = representation.json()["authorization_id"]
    assert client.post(
        f"/api/v1/representations/{authorization_id}/accept",
        headers=client_headers,
    ).status_code == 200

    opportunity = client.post(
        "/api/v1/opportunities",
        headers=originator_headers,
        json={
            "representation_authorization_id": authorization_id,
            "title": "Operação concorrente",
            "purpose": "Validar controle otimista",
        },
    )
    opportunity_id = opportunity.json()["opportunity_id"]

    first = client.post(
        f"/api/v1/opportunities/{opportunity_id}/qualification",
        headers={**analyst_headers, "If-Match": "1"},
        json={
            "result": "ELIGIBLE",
            "conclusion": "Primeira decisão.",
        },
    )
    assert first.status_code == 201

    stale = client.post(
        f"/api/v1/opportunities/{opportunity_id}/qualification",
        headers={**analyst_headers, "If-Match": "1"},
        json={
            "result": "INFORMATION_REQUIRED",
            "conclusion": "Atualização com versão antiga.",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

    with SessionLocal() as db:
        qualification_count = db.scalar(
            select(func.count())
            .select_from(QualificationCase)
            .where(QualificationCase.opportunity_id == opportunity_id)
        )
        opportunity_row = db.scalar(
            select(CapitalOpportunity).where(
                CapitalOpportunity.opportunity_id == opportunity_id
            )
        )
        assert qualification_count == 1
        assert opportunity_row is not None
        assert opportunity_row.version == 2
