from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

from app.integrations.efata.platform_v2_contracts import EfataV2StreamEvent


class EfataV2SseContractError(ValueError):
    pass


def _parse_event(
    *,
    event_name: str | None,
    data_lines: list[str],
    event_bytes: int,
    max_event_bytes: int,
) -> EfataV2StreamEvent:
    if event_name is None:
        raise EfataV2SseContractError("SSE_EVENT_NAME_REQUIRED")
    if event_bytes > max_event_bytes:
        raise EfataV2SseContractError("SSE_EVENT_TOO_LARGE")

    data_raw = "\n".join(data_lines).strip()
    try:
        payload = json.loads(data_raw) if data_raw else {}
    except json.JSONDecodeError as exc:
        raise EfataV2SseContractError("SSE_DATA_JSON_INVALID") from exc

    try:
        return EfataV2StreamEvent(
            event=event_name,
            data=payload,
        )
    except Exception as exc:
        raise EfataV2SseContractError("SSE_EVENT_CONTRACT_INVALID") from exc


def iter_sse_events(
    lines: Iterable[str | bytes],
    *,
    max_event_bytes: int = 1_048_576,
    max_events: int = 10_000,
) -> Iterator[EfataV2StreamEvent]:
    """Incrementally parse and validate an Efatà SSE stream.

    The parser does not buffer the full HTTP body. It buffers only the current
    SSE event and validates execution identity/sequence as events arrive.
    """
    event_name: str | None = None
    data_lines: list[str] = []
    event_bytes = 0
    event_count = 0
    expected_execution_id: str | None = None
    last_sequence: int | None = None
    done_seen = False

    def validate_progressive(event: EfataV2StreamEvent) -> None:
        nonlocal expected_execution_id, last_sequence, done_seen, event_count

        if done_seen:
            raise EfataV2SseContractError("SSE_EVENT_AFTER_DONE")

        event_count += 1
        if event_count > max_events:
            raise EfataV2SseContractError("SSE_EVENT_LIMIT_EXCEEDED")

        execution_id = event.execution_id
        if execution_id is not None:
            if expected_execution_id is None:
                expected_execution_id = execution_id
            elif execution_id != expected_execution_id:
                raise EfataV2SseContractError("SSE_EXECUTION_ID_MISMATCH")

        sequence = event.sequence
        if sequence is not None:
            if last_sequence is not None and sequence != last_sequence + 1:
                raise EfataV2SseContractError("SSE_SEQUENCE_MUST_BE_CONTIGUOUS")
            last_sequence = sequence

        if event.event == "done":
            done_seen = True

    def flush() -> EfataV2StreamEvent | None:
        nonlocal event_name, data_lines, event_bytes
        if event_name is None and not data_lines:
            return None
        event = _parse_event(
            event_name=event_name,
            data_lines=data_lines,
            event_bytes=event_bytes,
            max_event_bytes=max_event_bytes,
        )
        event_name = None
        data_lines = []
        event_bytes = 0
        validate_progressive(event)
        return event

    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r\n")

        if line == "":
            event = flush()
            if event is not None:
                yield event
            continue

        if line.startswith(":"):
            # SSE heartbeat/comment. It is not a semantic event.
            continue

        event_bytes += len(line.encode("utf-8")) + 1
        if event_bytes > max_event_bytes:
            raise EfataV2SseContractError("SSE_EVENT_TOO_LARGE")

        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
            continue

        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
            continue

        # Unknown SSE fields are ignored by the SSE spec. They cannot mutate
        # semantic identity because only event/data are consumed.

    event = flush()
    if event is not None:
        yield event

    if not done_seen:
        raise EfataV2SseContractError("SSE_TERMINAL_EVENT_REQUIRED")


def parse_sse_text(
    raw: str,
    *,
    max_event_bytes: int = 1_048_576,
    max_events: int = 10_000,
) -> list[EfataV2StreamEvent]:
    return list(
        iter_sse_events(
            raw.splitlines(),
            max_event_bytes=max_event_bytes,
            max_events=max_events,
        )
    )


def validate_terminal_contract(events: list[EfataV2StreamEvent]) -> None:
    """Compatibility validator for already-parsed event collections."""
    if not events:
        raise EfataV2SseContractError("SSE_TERMINAL_EVENT_REQUIRED")

    # Re-serialize through the same progressive invariants without relying on
    # the original HTTP body.
    done_positions = [
        index for index, event in enumerate(events)
        if event.event == "done"
    ]
    if done_positions != [len(events) - 1]:
        raise EfataV2SseContractError("SSE_DONE_MUST_BE_UNIQUE_AND_LAST")

    execution_ids = {
        event.execution_id
        for event in events
        if event.execution_id is not None
    }
    if len(execution_ids) > 1:
        raise EfataV2SseContractError("SSE_EXECUTION_ID_MISMATCH")

    sequences = [
        event.sequence
        for event in events
        if event.sequence is not None
    ]
    if sequences:
        for previous, current in zip(sequences, sequences[1:]):
            if current != previous + 1:
                raise EfataV2SseContractError("SSE_SEQUENCE_MUST_BE_CONTIGUOUS")
