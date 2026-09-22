from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings
from app.errors import ApiError
from app.integrations.efata.platform_v2_contracts import (
    EfataV2BridgeSnapshot,
    EfataV2KnowledgeDocument,
    EfataV2MessageCreate,
    EfataV2MessageResponse,
    EfataV2RequestObservation,
    EfataV2StreamEvent,
    EfataV2Thread,
)
from app.integrations.efata.platform_v2_sse import iter_sse_events


logger = logging.getLogger("fintech.integration.efata")


class EfataV2BridgeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.request_id = request_id
        self.correlation_id = correlation_id


_STATUS_CODE_MAP = {
    401: "AUTHENTICATION_FAILED",
    403: "AUTHORIZATION_FAILED",
    404: "CONTRACT_OR_RESOURCE_NOT_FOUND",
    409: "CONFLICT",
    429: "RATE_LIMITED",
}


def _http_result_code(status_code: int) -> str:
    if status_code in _STATUS_CODE_MAP:
        return _STATUS_CODE_MAP[status_code]
    if status_code >= 500:
        return "UPSTREAM_FAILURE"
    if status_code >= 400:
        return "UPSTREAM_REJECTED"
    return "OK"


class EfataPlatformV2Client:
    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        api_prefix: str = "/api/v2",
        default_agent: str = "Josué",
        timeout_seconds: float = 15.0,
        sse_max_event_bytes: int = 1_048_576,
        sse_max_events: int = 10_000,
        correlation_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        normalized_base = base_url.strip().rstrip("/")
        if not normalized_base.startswith(("http://", "https://")):
            raise EfataV2BridgeError(
                "EFATA_BASE_URL_INVALID",
                "Efatà base URL must use HTTP(S).",
            )
        if not access_token.strip():
            raise EfataV2BridgeError(
                "EFATA_ACCESS_TOKEN_REQUIRED",
                "A provisioned bearer token is required.",
            )
        if timeout_seconds <= 0:
            raise EfataV2BridgeError(
                "EFATA_TIMEOUT_INVALID",
                "Efatà timeout must be positive.",
            )
        if sse_max_event_bytes <= 0 or sse_max_events <= 0:
            raise EfataV2BridgeError(
                "EFATA_SSE_LIMIT_INVALID",
                "Efatà SSE limits must be positive.",
            )

        self.base_url = normalized_base
        self.api_prefix = "/" + api_prefix.strip("/")
        self.default_agent = default_agent
        self.timeout_seconds = timeout_seconds
        self.sse_max_event_bytes = sse_max_event_bytes
        self.sse_max_events = sse_max_events
        self.correlation_id = correlation_id or str(uuid4())
        self._observations: list[EfataV2RequestObservation] = []
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "Authorization": f"Bearer {access_token.strip()}",
                "Accept": "application/json",
                "User-Agent": "efata-fintech-r11.3-prep",
            },
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        correlation_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> "EfataPlatformV2Client":
        if not settings.efata_platform_bridge_enabled:
            raise ApiError(
                503,
                "EFATA_PLATFORM_BRIDGE_DISABLED",
                "A integração preview com a Plataforma Efatà está desabilitada.",
            )
        if not settings.efata_platform_base_url:
            raise ApiError(
                503,
                "EFATA_PLATFORM_BASE_URL_REQUIRED",
                "A URL da Plataforma Efatà não está configurada.",
            )
        if not settings.efata_platform_access_token:
            raise ApiError(
                503,
                "EFATA_PLATFORM_TOKEN_REQUIRED",
                "A credencial da Plataforma Efatà não está configurada.",
            )
        return cls(
            base_url=settings.efata_platform_base_url,
            access_token=settings.efata_platform_access_token,
            api_prefix=settings.efata_platform_api_prefix,
            default_agent=settings.efata_platform_default_agent,
            timeout_seconds=settings.efata_platform_timeout_seconds,
            sse_max_event_bytes=settings.efata_platform_sse_max_event_bytes,
            sse_max_events=settings.efata_platform_sse_max_events,
            correlation_id=correlation_id,
            transport=transport,
        )

    @property
    def observations(self) -> tuple[EfataV2RequestObservation, ...]:
        return tuple(self._observations)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EfataPlatformV2Client":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _url(self, suffix: str) -> str:
        return f"{self.api_prefix}/{suffix.lstrip('/')}"

    def _safe_headers(
        self,
        *,
        request_id: str,
        correlation_id: str,
        accept: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "X-Request-ID": request_id,
            "X-Correlation-ID": correlation_id,
        }
        if accept:
            headers["Accept"] = accept
        return headers

    def _observe(
        self,
        *,
        request_id: str,
        correlation_id: str,
        method: str,
        path: str,
        status_code: int | None,
        duration_ms: float,
        result_code: str,
    ) -> None:
        observation = EfataV2RequestObservation(
            request_id=request_id,
            correlation_id=correlation_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            result_code=result_code,
        )
        self._observations.append(observation)
        # Bound local diagnostic memory. Never store headers, token or body.
        if len(self._observations) > 100:
            del self._observations[:-100]

        log_method = logger.info if result_code == "OK" else logger.warning
        log_method(
            "EFATA_UPSTREAM_REQUEST_COMPLETED",
            extra={
                "request_id": request_id,
                "correlation_id": correlation_id,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "event_code": f"EFATA_{result_code}",
            },
        )

    def _bridge_error(
        self,
        *,
        code: str,
        status_code: int | None,
        request_id: str,
        correlation_id: str,
    ) -> EfataV2BridgeError:
        # Do not include response body, Authorization header, raw token or URL
        # query data in user/log-visible errors.
        return EfataV2BridgeError(
            code,
            f"Efatà Platform request failed: {code}.",
            status_code=status_code,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _request(
        self,
        method: str,
        suffix: str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        **kwargs,
    ) -> httpx.Response:
        rid = request_id or str(uuid4())
        cid = correlation_id or self.correlation_id
        path = self._url(suffix)
        started = perf_counter()

        provided_headers = dict(kwargs.pop("headers", {}) or {})
        headers = self._safe_headers(
            request_id=rid,
            correlation_id=cid,
            accept=provided_headers.pop("Accept", None),
        )
        headers.update(provided_headers)

        try:
            response = self._client.request(
                method,
                path,
                headers=headers,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            duration = round((perf_counter() - started) * 1000, 3)
            self._observe(
                request_id=rid,
                correlation_id=cid,
                method=method,
                path=path,
                status_code=None,
                duration_ms=duration,
                result_code="UPSTREAM_TIMEOUT",
            )
            raise self._bridge_error(
                code="UPSTREAM_TIMEOUT",
                status_code=None,
                request_id=rid,
                correlation_id=cid,
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            duration = round((perf_counter() - started) * 1000, 3)
            self._observe(
                request_id=rid,
                correlation_id=cid,
                method=method,
                path=path,
                status_code=None,
                duration_ms=duration,
                result_code="UPSTREAM_UNAVAILABLE",
            )
            raise self._bridge_error(
                code="UPSTREAM_UNAVAILABLE",
                status_code=None,
                request_id=rid,
                correlation_id=cid,
            ) from exc
        except httpx.HTTPError as exc:
            duration = round((perf_counter() - started) * 1000, 3)
            self._observe(
                request_id=rid,
                correlation_id=cid,
                method=method,
                path=path,
                status_code=None,
                duration_ms=duration,
                result_code="UPSTREAM_TRANSPORT_ERROR",
            )
            raise self._bridge_error(
                code="UPSTREAM_TRANSPORT_ERROR",
                status_code=None,
                request_id=rid,
                correlation_id=cid,
            ) from exc

        duration = round((perf_counter() - started) * 1000, 3)
        result_code = _http_result_code(response.status_code)
        self._observe(
            request_id=rid,
            correlation_id=cid,
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration,
            result_code=result_code,
        )

        if response.is_error:
            raise self._bridge_error(
                code=result_code,
                status_code=response.status_code,
                request_id=rid,
                correlation_id=cid,
            )

        return response

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise EfataV2BridgeError(
                "UPSTREAM_RESPONSE_INVALID",
                "Efatà Platform returned an invalid JSON response.",
                status_code=response.status_code,
            ) from exc

    def health(self) -> dict[str, Any]:
        return self._json(self._request("GET", "health"))

    def ready(self) -> dict[str, Any]:
        return self._json(self._request("GET", "ready"))

    def list_tool_capabilities(self) -> dict[str, Any] | list[Any]:
        return self._json(self._request("GET", "tools/capabilities"))

    def realtime_capabilities(self) -> dict[str, Any] | list[Any]:
        return self._json(self._request("GET", "realtime/capabilities"))

    def probe(self) -> EfataV2BridgeSnapshot:
        return EfataV2BridgeSnapshot(
            health=self.health(),
            ready=self.ready(),
            tools_capabilities=self.list_tool_capabilities(),
            realtime_capabilities=self.realtime_capabilities(),
        )

    def create_thread(self, *, title: str) -> EfataV2Thread:
        response = self._request(
            "POST",
            "threads",
            json={"title": title},
        )
        return EfataV2Thread.model_validate(self._json(response))

    def send_message(
        self,
        *,
        thread_id: str,
        content: str,
        agent: str | None = None,
    ) -> EfataV2MessageResponse:
        payload = EfataV2MessageCreate(
            content=content,
            agent=agent or self.default_agent,
        )
        response = self._request(
            "POST",
            f"threads/{thread_id}/messages",
            json=payload.model_dump(),
        )
        return EfataV2MessageResponse.model_validate(self._json(response))

    def iter_stream_message(
        self,
        *,
        thread_id: str,
        content: str,
        agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Iterator[EfataV2StreamEvent]:
        payload = EfataV2MessageCreate(
            content=content,
            agent=agent or self.default_agent,
        )
        rid = request_id or str(uuid4())
        cid = correlation_id or self.correlation_id
        path = self._url(f"threads/{thread_id}/stream")
        started = perf_counter()

        try:
            with self._client.stream(
                "POST",
                path,
                json=payload.model_dump(),
                headers=self._safe_headers(
                    request_id=rid,
                    correlation_id=cid,
                    accept="text/event-stream",
                ),
            ) as response:
                if response.is_error:
                    duration = round((perf_counter() - started) * 1000, 3)
                    result_code = _http_result_code(response.status_code)
                    self._observe(
                        request_id=rid,
                        correlation_id=cid,
                        method="POST",
                        path=path,
                        status_code=response.status_code,
                        duration_ms=duration,
                        result_code=result_code,
                    )
                    raise self._bridge_error(
                        code=result_code,
                        status_code=response.status_code,
                        request_id=rid,
                        correlation_id=cid,
                    )

                for event in iter_sse_events(
                    response.iter_lines(),
                    max_event_bytes=self.sse_max_event_bytes,
                    max_events=self.sse_max_events,
                ):
                    yield event

                duration = round((perf_counter() - started) * 1000, 3)
                self._observe(
                    request_id=rid,
                    correlation_id=cid,
                    method="POST",
                    path=path,
                    status_code=response.status_code,
                    duration_ms=duration,
                    result_code="OK",
                )
        except EfataV2BridgeError:
            raise
        except httpx.TimeoutException as exc:
            duration = round((perf_counter() - started) * 1000, 3)
            self._observe(
                request_id=rid,
                correlation_id=cid,
                method="POST",
                path=path,
                status_code=None,
                duration_ms=duration,
                result_code="UPSTREAM_TIMEOUT",
            )
            raise self._bridge_error(
                code="UPSTREAM_TIMEOUT",
                status_code=None,
                request_id=rid,
                correlation_id=cid,
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            duration = round((perf_counter() - started) * 1000, 3)
            self._observe(
                request_id=rid,
                correlation_id=cid,
                method="POST",
                path=path,
                status_code=None,
                duration_ms=duration,
                result_code="UPSTREAM_UNAVAILABLE",
            )
            raise self._bridge_error(
                code="UPSTREAM_UNAVAILABLE",
                status_code=None,
                request_id=rid,
                correlation_id=cid,
            ) from exc

    def stream_message(
        self,
        *,
        thread_id: str,
        content: str,
        agent: str | None = None,
    ) -> list[EfataV2StreamEvent]:
        # Compatibility helper. Real network integrations should consume
        # iter_stream_message() incrementally.
        return list(
            self.iter_stream_message(
                thread_id=thread_id,
                content=content,
                agent=agent,
            )
        )

    def upload_knowledge(
        self,
        *,
        file_path: Path,
        scope: str = "INSTITUTIONAL",
        title: str | None = None,
        classification: str = "internal",
        allowed_purposes: tuple[str, ...] = ("chat", "team", "realtime"),
        agent_id: str | None = None,
    ) -> EfataV2KnowledgeDocument:
        path = file_path.resolve()
        if not path.is_file():
            raise EfataV2BridgeError(
                "EFATA_KNOWLEDGE_FILE_NOT_FOUND",
                f"Knowledge file not found: {path}",
            )

        data = {
            "scope": scope,
            "title": title or path.stem,
            "classification": classification,
            "allowed_purposes": ",".join(allowed_purposes),
        }
        if agent_id:
            data["agent_id"] = agent_id

        response = self._request(
            "POST",
            "knowledge",
            data=data,
            files={
                "file": (
                    path.name,
                    path.read_bytes(),
                    "text/markdown"
                    if path.suffix.lower() in {".md", ".markdown"}
                    else "application/octet-stream",
                )
            },
        )
        return EfataV2KnowledgeDocument.model_validate(self._json(response))

    def list_knowledge(
        self,
        *,
        scope: str = "INSTITUTIONAL",
    ) -> list[EfataV2KnowledgeDocument]:
        response = self._request(
            "GET",
            "knowledge",
            params={"scope": scope},
        )
        payload = self._json(response)
        return [
            EfataV2KnowledgeDocument.model_validate(item)
            for item in payload.get("items", [])
        ]

    def get_knowledge_content(
        self,
        *,
        document_id: str,
        max_chars: int = 100_000,
    ) -> dict[str, Any]:
        return self._json(
            self._request(
                "GET",
                f"knowledge/{document_id}/content",
                params={"max_chars": max_chars},
            )
        )

    def publish_knowledge(
        self,
        *,
        document_id: str,
    ) -> EfataV2KnowledgeDocument:
        response = self._request(
            "POST",
            f"knowledge/{document_id}/publish",
        )
        return EfataV2KnowledgeDocument.model_validate(self._json(response))

    def revoke_knowledge(
        self,
        *,
        document_id: str,
    ) -> EfataV2KnowledgeDocument:
        response = self._request(
            "POST",
            f"knowledge/{document_id}/revoke",
        )
        return EfataV2KnowledgeDocument.model_validate(self._json(response))

    def delete_knowledge_draft(
        self,
        *,
        document_id: str,
    ) -> dict[str, Any]:
        return self._json(
            self._request(
                "DELETE",
                f"knowledge/{document_id}",
            )
        )
