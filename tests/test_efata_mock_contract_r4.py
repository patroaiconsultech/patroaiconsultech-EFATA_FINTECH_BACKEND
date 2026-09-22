from app.config import Settings
from app.errors import ApiError
from app.integrations.efata.contracts import EfataExecutionRequest
from app.integrations.efata.factory import get_efata_adapter


def test_mock_efata_contract_has_terminal_done():
    adapter = get_efata_adapter(
        Settings(
            app_env="test",
            efata_mode="mock",
            database_url="sqlite://",
        )
    )
    envelope = adapter.submit_execution(
        EfataExecutionRequest(
            request_id="request-1",
            correlation_id="correlation-1",
            tenant_id="tenant-1",
            user_id="user-1",
            capability_id="mock.document_preliminary_analysis",
            purpose="QUALIFICATION_SUPPORT",
            data_classification="CONFIDENTIAL",
            persist_to_platform_memory=False,
            write_allowed=False,
            payload={"document_id": "document-1"},
        )
    )

    assert envelope.status == "completed"
    assert envelope.content["memory_persisted"] is False
    assert envelope.content["write_executed"] is False

    events = list(adapter.stream_execution(envelope.execution_id))
    assert [event.event for event in events] == ["agent_done", "done"]
    assert events[-1].payload["terminal"] is True


def test_real_efata_adapter_is_disabled_in_r4():
    try:
        get_efata_adapter(
            Settings(
                app_env="test",
                efata_mode="sandbox",
                database_url="sqlite://",
            )
        )
    except ApiError as exc:
        assert exc.status_code == 503
        assert exc.code == "EFATA_REAL_INTEGRATION_DISABLED"
    else:
        raise AssertionError("Real Efatà integration unexpectedly enabled.")
