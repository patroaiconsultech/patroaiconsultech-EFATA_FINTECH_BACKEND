from sqlalchemy import select

from app.db import SessionLocal
from app.models import ResourceGrant


def create_active_opportunity(client, ids, auth_headers, allowed_actions):
    originator_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    client_headers = auth_headers(ids["client_user"], ids["client_tenant"])

    lead = client.post(
        "/api/v1/leads",
        headers=originator_headers,
        json={
            "prospective_client_name": "Empresa Escopo",
            "opportunity_type": "STRUCTURED_CREDIT",
            "estimated_amount": "1000000.00",
            "currency": "BRL",
        },
    )
    assert lead.status_code == 201

    representation = client.post(
        "/api/v1/representations",
        headers=originator_headers,
        json={
            "lead_id": lead.json()["lead_id"],
            "represented_tenant_id": ids["client_tenant"],
            "allowed_actions": allowed_actions,
        },
    )
    assert representation.status_code == 201
    authorization_id = representation.json()["authorization_id"]

    accepted = client.post(
        f"/api/v1/representations/{authorization_id}/accept",
        headers=client_headers,
    )
    assert accepted.status_code == 200

    opportunity = client.post(
        "/api/v1/opportunities",
        headers=originator_headers,
        json={
            "representation_authorization_id": authorization_id,
            "title": "Operação de escopo",
            "purpose": "Validar o ciclo de autorização",
        },
    )
    assert opportunity.status_code == 201
    return authorization_id, opportunity.json()["opportunity_id"]


def test_scope_without_upload_does_not_grant_upload(client, ids, auth_headers):
    originator_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    authorization_id, opportunity_id = create_active_opportunity(
        client,
        ids,
        auth_headers,
        ["CREATE_OPPORTUNITY", "VIEW_STATUS"],
    )

    read_response = client.get(
        f"/api/v1/opportunities/{opportunity_id}",
        headers=originator_headers,
    )
    assert read_response.status_code == 200

    upload_response = client.post(
        f"/api/v1/opportunities/{opportunity_id}/documents",
        headers=originator_headers,
        json={
            "filename": "nao-autorizado.pdf",
            "document_type": "FINANCIAL_STATEMENT",
            "checksum_sha256": "b" * 64,
        },
    )
    assert upload_response.status_code == 404

    with SessionLocal() as db:
        grant = db.scalar(
            select(ResourceGrant).where(
                ResourceGrant.source_type == "REPRESENTATION_AUTHORIZATION",
                ResourceGrant.source_id == authorization_id,
            )
        )
        assert grant is not None
        assert grant.permissions == ["READ"]


def test_revocation_revokes_derived_grants_and_access(client, ids, auth_headers):
    originator_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    client_headers = auth_headers(ids["client_user"], ids["client_tenant"])

    authorization_id, opportunity_id = create_active_opportunity(
        client,
        ids,
        auth_headers,
        ["CREATE_OPPORTUNITY", "VIEW_STATUS", "UPLOAD_DOCUMENTS"],
    )

    before = client.get(
        f"/api/v1/opportunities/{opportunity_id}",
        headers=originator_headers,
    )
    assert before.status_code == 200

    revoked = client.post(
        f"/api/v1/representations/{authorization_id}/revoke",
        headers=client_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "REVOKED"

    after_read = client.get(
        f"/api/v1/opportunities/{opportunity_id}",
        headers=originator_headers,
    )
    assert after_read.status_code == 404

    after_upload = client.post(
        f"/api/v1/opportunities/{opportunity_id}/documents",
        headers=originator_headers,
        json={
            "filename": "revogado.pdf",
            "document_type": "FINANCIAL_STATEMENT",
            "checksum_sha256": "c" * 64,
        },
    )
    assert after_upload.status_code == 404

    with SessionLocal() as db:
        grant = db.scalar(
            select(ResourceGrant).where(
                ResourceGrant.source_type == "REPRESENTATION_AUTHORIZATION",
                ResourceGrant.source_id == authorization_id,
            )
        )
        assert grant is not None
        assert grant.status == "REVOKED"
        assert grant.revoked_at is not None


def test_non_client_admin_cannot_accept_representation(client, ids, auth_headers):
    originator_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    analyst_headers = auth_headers(ids["analyst_user"], ids["platform_tenant"])

    lead = client.post(
        "/api/v1/leads",
        headers=originator_headers,
        json={
            "prospective_client_name": "Empresa Papel",
            "opportunity_type": "STRUCTURED_CREDIT",
            "estimated_amount": "2000000.00",
            "currency": "BRL",
        },
    )
    representation = client.post(
        "/api/v1/representations",
        headers=originator_headers,
        json={
            "lead_id": lead.json()["lead_id"],
            "represented_tenant_id": ids["client_tenant"],
            "allowed_actions": ["CREATE_OPPORTUNITY"],
        },
    )

    response = client.post(
        f"/api/v1/representations/{representation.json()['authorization_id']}/accept",
        headers=analyst_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


def test_local_cors_preflight_is_restricted(client):
    response = client.options(
        "/api/v1/leads",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-user-id,x-tenant-id",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
