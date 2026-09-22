from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import AuditEvent


def test_minimum_and_premium_vertical_slice(client, ids, auth_headers):
    originator_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    client_headers = auth_headers(ids["client_user"], ids["client_tenant"])
    analyst_headers = auth_headers(ids["analyst_user"], ids["platform_tenant"])
    foreign_headers = auth_headers(ids["foreign_user"], ids["foreign_tenant"])

    lead_response = client.post(
        "/api/v1/leads",
        headers=originator_headers,
        json={
            "prospective_client_name": "Empresa Alpha",
            "opportunity_type": "STRUCTURED_CREDIT",
            "estimated_amount": "5000000.00",
            "currency": "BRL",
        },
    )
    assert lead_response.status_code == 201
    lead_id = lead_response.json()["lead_id"]

    representation_response = client.post(
        "/api/v1/representations",
        headers=originator_headers,
        json={
            "lead_id": lead_id,
            "represented_tenant_id": ids["client_tenant"],
            "allowed_actions": ["CREATE_OPPORTUNITY", "UPLOAD_DOCUMENTS", "VIEW_STATUS"],
        },
    )
    assert representation_response.status_code == 201
    authorization_id = representation_response.json()["authorization_id"]

    accept_response = client.post(
        f"/api/v1/representations/{authorization_id}/accept",
        headers=client_headers,
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["status"] == "ACTIVE"

    opportunity_response = client.post(
        "/api/v1/opportunities",
        headers=originator_headers,
        json={
            "representation_authorization_id": authorization_id,
            "title": "Capital de giro com garantia",
            "purpose": "Expansão da capacidade operacional",
        },
    )
    assert opportunity_response.status_code == 201
    opportunity_id = opportunity_response.json()["opportunity_id"]
    assert opportunity_response.json()["tenant_id"] == ids["client_tenant"]

    document_response = client.post(
        f"/api/v1/opportunities/{opportunity_id}/documents",
        headers=originator_headers,
        json={
            "filename": "balanco.pdf",
            "document_type": "FINANCIAL_STATEMENT",
            "checksum_sha256": "a" * 64,
        },
    )
    assert document_response.status_code == 201
    assert document_response.json()["processing_status"] == "MOCK_ACCEPTED"

    foreign_response = client.get(
        f"/api/v1/opportunities/{opportunity_id}",
        headers=foreign_headers,
    )
    assert foreign_response.status_code == 404
    assert foreign_response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    qualification_response = client.post(
        f"/api/v1/opportunities/{opportunity_id}/qualification",
        headers={**analyst_headers, "If-Match": "1"},
        json={
            "result": "ELIGIBLE",
            "conclusion": "Informações mínimas consistentes para avançar.",
        },
    )
    assert qualification_response.status_code == 201

    client_view = client.get(
        f"/api/v1/opportunities/{opportunity_id}",
        headers=client_headers,
    )
    assert client_view.status_code == 200
    assert client_view.json()["stage"] == "QUALIFIED"

    with SessionLocal() as db:
        audit_count = db.scalar(select(func.count()).select_from(AuditEvent))
        assert audit_count >= 5
