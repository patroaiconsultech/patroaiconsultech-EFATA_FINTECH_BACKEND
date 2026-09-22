from __future__ import annotations

import logging

import httpx
import pytest

from app.integrations.efata.platform_v2_client import (
    EfataPlatformV2Client,
    EfataV2BridgeError,
)
from app.integrations.efata.platform_v2_sse import (
    EfataV2SseContractError,
    parse_sse_text,
)


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "AUTHENTICATION_FAILED"),
        (403, "AUTHORIZATION_FAILED"),
        (404, "CONTRACT_OR_RESOURCE_NOT_FOUND"),
        (409, "CONFLICT"),
        (429, "RATE_LIMITED"),
        (422, "UPSTREAM_REJECTED"),
        (500, "UPSTREAM_FAILURE"),
        (503, "UPSTREAM_FAILURE"),
    ],
)
def test_http_error_taxonomy(status_code, expected):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, json={"detail": "SENSITIVE"})
    )
    with EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="super-secret-token",
        transport=transport,
    ) as client:
        with pytest.raises(EfataV2BridgeError) as captured:
            client.health()

    assert captured.value.code == expected
    assert captured.value.status_code == status_code
    assert "SENSITIVE" not in str(captured.value)
    assert "super-secret-token" not in str(captured.value)


def test_timeout_maps_without_exposing_token(caplog):
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("secret-token-must-not-leak", request=request)

    caplog.set_level(logging.INFO)
    with EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="secret-token-must-not-leak",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(EfataV2BridgeError) as captured:
            client.health()

    assert captured.value.code == "UPSTREAM_TIMEOUT"
    assert "secret-token-must-not-leak" not in caplog.text
    assert "Authorization" not in caplog.text


def test_connection_error_maps_to_unavailable():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("network down", request=request)

    with EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(EfataV2BridgeError) as captured:
            client.health()

    assert captured.value.code == "UPSTREAM_UNAVAILABLE"


def test_request_and_correlation_ids_are_propagated_and_observed():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    with EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="token",
        correlation_id="corr-113",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.health()["status"] == "ok"
        observations = client.observations

    assert len(seen) == 1
    assert seen[0].headers["X-Correlation-ID"] == "corr-113"
    assert seen[0].headers["X-Request-ID"]
    assert observations[0].correlation_id == "corr-113"
    assert observations[0].request_id == seen[0].headers["X-Request-ID"]
    assert observations[0].result_code == "OK"
    assert observations[0].duration_ms >= 0


def valid_stream(*extra_lines: str) -> str:
    base = [
        ": heartbeat",
        "event: status",
        'data: {"execution_id":"e1","sequence":1,"status":"started"}',
        "",
        "event: chunk",
        'data: {"execution_id":"e1","sequence":2,',
        'data: "text":"hello"}',
        "",
    ]
    base.extend(extra_lines)
    return "\n".join(base)


def test_sse_accepts_heartbeat_and_multiline_data():
    raw = valid_stream(
        "event: done",
        'data: {"execution_id":"e1","sequence":3,"status":"completed"}',
        "",
    )
    events = parse_sse_text(raw)
    assert [e.event for e in events] == ["status", "chunk", "done"]
    assert events[1].data["text"] == "hello"


def test_sse_unknown_event_rejected():
    raw = "\n".join([
        "event: unknown_event",
        'data: {"execution_id":"e1","sequence":1}',
        "",
        "event: done",
        'data: {"execution_id":"e1","sequence":2}',
        "",
    ])
    with pytest.raises(EfataV2SseContractError) as captured:
        parse_sse_text(raw)
    assert str(captured.value) == "SSE_EVENT_CONTRACT_INVALID"


@pytest.mark.parametrize(
    "raw",
    [
        # no done / interrupted
        "\n".join([
            "event: status",
            'data: {"execution_id":"e1","sequence":1}',
            "",
        ]),
        # repeated sequence
        "\n".join([
            "event: status",
            'data: {"execution_id":"e1","sequence":1}',
            "",
            "event: chunk",
            'data: {"execution_id":"e1","sequence":1}',
            "",
            "event: done",
            'data: {"execution_id":"e1","sequence":2}',
            "",
        ]),
        # regressive sequence
        "\n".join([
            "event: status",
            'data: {"execution_id":"e1","sequence":2}',
            "",
            "event: chunk",
            'data: {"execution_id":"e1","sequence":1}',
            "",
            "event: done",
            'data: {"execution_id":"e1","sequence":2}',
            "",
        ]),
        # execution id drift
        "\n".join([
            "event: status",
            'data: {"execution_id":"e1","sequence":1}',
            "",
            "event: done",
            'data: {"execution_id":"e2","sequence":2}',
            "",
        ]),
        # duplicate / event after done
        "\n".join([
            "event: done",
            'data: {"execution_id":"e1","sequence":1}',
            "",
            "event: done",
            'data: {"execution_id":"e1","sequence":2}',
            "",
        ]),
    ],
)
def test_sse_adversarial_contracts_are_rejected(raw):
    with pytest.raises(EfataV2SseContractError):
        parse_sse_text(raw)


def test_sse_truncated_json_rejected():
    raw = "\n".join([
        "event: status",
        'data: {"execution_id":"e1","sequence":1',
        "",
    ])
    with pytest.raises(EfataV2SseContractError) as captured:
        parse_sse_text(raw)
    assert str(captured.value) == "SSE_DATA_JSON_INVALID"


def test_sse_event_size_limit():
    raw = "\n".join([
        "event: chunk",
        'data: {"execution_id":"e1","sequence":1,"text":"' + ("x" * 100) + '"}',
        "",
        "event: done",
        'data: {"execution_id":"e1","sequence":2}',
        "",
    ])
    with pytest.raises(EfataV2SseContractError) as captured:
        parse_sse_text(raw, max_event_bytes=80)
    assert str(captured.value) == "SSE_EVENT_TOO_LARGE"


def test_http_200_with_semantically_invalid_stream_fails():
    invalid_sse = "\n".join([
        "event: status",
        'data: {"execution_id":"e1","sequence":1}',
        "",
    ])

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=invalid_sse,
        )

    with EfataPlatformV2Client(
        base_url="https://efata.example",
        access_token="token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(EfataV2SseContractError) as captured:
            list(
                client.iter_stream_message(
                    thread_id="thread-1",
                    content="synthetic",
                )
            )

    assert str(captured.value) == "SSE_TERMINAL_EVENT_REQUIRED"
