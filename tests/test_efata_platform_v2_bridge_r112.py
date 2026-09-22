from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.errors import ApiError
from app.integrations.efata.platform_v2_client import (
    EfataPlatformV2Client,
)
from app.integrations.efata.platform_v2_sse import (
    EfataV2SseContractError,
    parse_sse_text,
)


def test_bridge_is_fail_closed_by_default():
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        efata_platform_bridge_enabled=False,
    )
    with pytest.raises(ApiError) as captured:
        EfataPlatformV2Client.from_settings(settings)
    assert captured.value.code == "EFATA_PLATFORM_BRIDGE_DISABLED"


def test_client_uses_api_v2_and_bearer():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v2/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/v2/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/api/v2/tools/capabilities":
            return httpx.Response(200, json={"capabilities": []})
        if request.url.path == "/api/v2/realtime/capabilities":
            return httpx.Response(200, json={"realtime": True})
        return httpx.Response(404)

    client = EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="token-preview",
        transport=httpx.MockTransport(handler),
    )
    snapshot = client.probe()
    client.close()

    assert snapshot.health["status"] == "ok"
    assert len(seen) == 4
    assert all(
        request.headers["Authorization"] == "Bearer token-preview"
        for request in seen
    )
    assert [request.url.path for request in seen] == [
        "/api/v2/health",
        "/api/v2/ready",
        "/api/v2/tools/capabilities",
        "/api/v2/realtime/capabilities",
    ]


def test_thread_and_message_contract_match_platform_baseline():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/threads":
            assert json.loads(request.content) == {"title": "Fintech Preview"}
            return httpx.Response(
                200,
                json={"id": "thread-1", "title": "Fintech Preview"},
            )

        if request.url.path == "/api/v2/threads/thread-1/messages":
            assert json.loads(request.content) == {
                "content": "Analise esta oportunidade.",
                "agent": "Josué",
            }
            return httpx.Response(
                200,
                json={
                    "message_id": "message-1",
                    "execution_id": "execution-1",
                    "agent_id": "josue",
                    "agent_name": "Josué",
                    "content": "Resposta.",
                    "execution": {
                        "request_id": "request-1",
                        "execution_id": "execution-1",
                        "resolved_target": "josue",
                        "turn_owner": "josue",
                        "display_agent_id": "josue",
                        "execution_engine": "direct",
                        "ownership_locked": True,
                    },
                    "response": {
                        "message_id": "message-1",
                        "execution_id": "execution-1",
                        "thread_id": "thread-1",
                        "tenant_id": "tenant-1",
                        "agent_id": "josue",
                        "agent_name": "Josué",
                        "display_name": "Josué",
                        "final_speaker_agent_id": "josue",
                        "turn_owner_agent_id": "josue",
                        "route_family": "direct",
                        "content": "Resposta.",
                        "status": "completed",
                        "error": None,
                        "token_usage": None,
                        "latency_ms": 10,
                        "created_at": "2026-09-17T12:00:00Z",
                    },
                },
            )
        return httpx.Response(404)

    with EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="token-preview",
        transport=httpx.MockTransport(handler),
    ) as client:
        thread = client.create_thread(title="Fintech Preview")
        response = client.send_message(
            thread_id=thread.id,
            content="Analise esta oportunidade.",
        )

    assert response.execution.ownership_locked is True
    assert response.response.turn_owner_agent_id == "josue"
    assert response.response.tenant_id == "tenant-1"


def test_sse_requires_unique_terminal_done():
    raw = "\n".join([
        "event: status",
        'data: {"execution_id":"e1","sequence":1,"status":"started"}',
        "",
        "event: chunk",
        'data: {"execution_id":"e1","sequence":2,"text":"Olá"}',
        "",
        "event: done",
        'data: {"execution_id":"e1","sequence":3,"status":"completed"}',
        "",
    ])
    events = parse_sse_text(raw)
    assert [event.event for event in events] == ["status", "chunk", "done"]

    invalid = raw + "\n".join([
        "event: done",
        'data: {"execution_id":"e1","sequence":4,"status":"completed"}',
        "",
    ])
    with pytest.raises(EfataV2SseContractError):
        parse_sse_text(invalid)


def test_error_must_precede_done():
    raw = "\n".join([
        "event: error",
        'data: {"execution_id":"e1","sequence":1,"code":"LLM_UPSTREAM_ERROR"}',
        "",
        "event: done",
        'data: {"execution_id":"e1","sequence":2,"status":"failed"}',
        "",
    ])
    events = parse_sse_text(raw)
    assert [event.event for event in events] == ["error", "done"]


def test_knowledge_upload_uses_institutional_scope(tmp_path: Path):
    master = tmp_path / "master.md"
    master.write_text("# Master Plan", encoding="utf-8")

    seen: dict[str, bytes | str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "id": "doc-1",
                "logical_document_id": "logical-1",
                "version": 1,
                "scope": "INSTITUTIONAL",
                "title": "Efatà Fintech — Master Plan Comercial",
                "filename": "master.md",
                "classification": "internal",
                "status": "DRAFT",
                "allowed_purposes": ["chat", "team", "realtime"],
            },
        )

    with EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="token-preview",
        transport=httpx.MockTransport(handler),
    ) as client:
        document = client.upload_knowledge(
            file_path=master,
            title="Efatà Fintech — Master Plan Comercial",
        )

    assert seen["path"] == "/api/v2/knowledge"
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b'INSTITUTIONAL' in body
    assert b'internal' in body
    assert b'chat,team,realtime' in body
    assert document.status == "DRAFT"
