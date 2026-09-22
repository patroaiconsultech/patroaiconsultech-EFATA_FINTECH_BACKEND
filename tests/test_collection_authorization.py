from tests.test_authorization_lifecycle import create_active_opportunity


def test_update_only_grant_does_not_expose_opportunity_in_collection(
    client,
    ids,
    auth_headers,
):
    originator_headers = auth_headers(
        ids["originator_user"],
        ids["originator_tenant"],
    )
    _, opportunity_id = create_active_opportunity(
        client,
        ids,
        auth_headers,
        ["CREATE_OPPORTUNITY", "UPDATE_OPPORTUNITY"],
    )

    collection = client.get(
        "/api/v1/opportunities",
        headers=originator_headers,
    )
    assert collection.status_code == 200
    assert opportunity_id not in {
        item["opportunity_id"]
        for item in collection.json()
    }

    detail = client.get(
        f"/api/v1/opportunities/{opportunity_id}",
        headers=originator_headers,
    )
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
