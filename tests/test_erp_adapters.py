import httpx
import pytest

from app.erp_adapters import ERPAdapterSecurityError, ReadOnlyERPAdapter


def test_read_only_adapter_fetches_resources_and_returns_hashes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.headers["X-External-Tenant"] == "tenant-demo"
        if request.url.path == "/api/projects":
            return httpx.Response(200, json={"data": [{"id": "p-1"}]})
        return httpx.Response(200, json={"items": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = ReadOnlyERPAdapter(
        provider="SIENGE",
        base_url="https://erp.example.test",
        external_tenant="tenant-demo",
        secret="api-user:api-password",
        resource_map={"projects": "/api/projects", "units": "/api/units"},
        allowed_hosts="erp.example.test",
        http_client=client,
    )

    result = adapter.sync(request_id="request-1", correlation_id="correlation-1")

    assert result.records_seen == 1
    assert len(result.resources) == 2
    assert result.resources[0].payload_hash.startswith("sha256:")
    assert any("units" in warning for warning in result.warnings)
    client.close()


def test_read_only_adapter_rejects_unapproved_host():
    with pytest.raises(ERPAdapterSecurityError):
        ReadOnlyERPAdapter(
            provider="MEGA",
            base_url="https://internal.example.test",
            external_tenant="tenant-demo",
            secret="token-value",
            resource_map={"projects": "/projects"},
            allowed_hosts="approved.example.test",
        )


def test_read_only_adapter_rejects_unsafe_resource_path():
    with pytest.raises(ERPAdapterSecurityError):
        ReadOnlyERPAdapter(
            provider="MEGA",
            base_url="https://erp.example.test",
            external_tenant="tenant-demo",
            secret="token-value",
            resource_map={"projects": "https://other.example.test/projects"},
            allowed_hosts="erp.example.test",
        )
