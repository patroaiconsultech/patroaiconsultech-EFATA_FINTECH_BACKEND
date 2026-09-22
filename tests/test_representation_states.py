def create_pending_representation(client, ids, auth_headers):
    originator_headers = auth_headers(
        ids["originator_user"],
        ids["originator_tenant"],
    )
    lead = client.post(
        "/api/v1/leads",
        headers=originator_headers,
        json={
            "prospective_client_name": "Empresa Estado",
            "opportunity_type": "STRUCTURED_CREDIT",
            "estimated_amount": "1500000.00",
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
            "allowed_actions": ["CREATE_OPPORTUNITY", "VIEW_STATUS"],
        },
    )
    assert representation.status_code == 201
    return representation.json()["authorization_id"]


def test_pending_representation_cannot_be_revoked(
    client,
    ids,
    auth_headers,
):
    client_headers = auth_headers(
        ids["client_user"],
        ids["client_tenant"],
    )
    authorization_id = create_pending_representation(
        client,
        ids,
        auth_headers,
    )

    response = client.post(
        f"/api/v1/representations/{authorization_id}/revoke",
        headers=client_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPRESENTATION_NOT_ACTIVE"


def test_revoked_representation_cannot_be_revoked_twice(
    client,
    ids,
    auth_headers,
):
    client_headers = auth_headers(
        ids["client_user"],
        ids["client_tenant"],
    )
    authorization_id = create_pending_representation(
        client,
        ids,
        auth_headers,
    )

    accepted = client.post(
        f"/api/v1/representations/{authorization_id}/accept",
        headers=client_headers,
    )
    assert accepted.status_code == 200

    first = client.post(
        f"/api/v1/representations/{authorization_id}/revoke",
        headers=client_headers,
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/representations/{authorization_id}/revoke",
        headers=client_headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "REPRESENTATION_NOT_ACTIVE"
