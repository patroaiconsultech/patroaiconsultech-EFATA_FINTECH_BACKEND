from typing import Protocol, Iterable

from app.integrations.efata.contracts import (
    EfataExecutionEnvelope,
    EfataExecutionRequest,
    EfataStreamEvent,
)


class FintechEfataPort(Protocol):
    def list_capabilities(self) -> list[dict]:
        ...

    def submit_execution(
        self,
        request: EfataExecutionRequest,
    ) -> EfataExecutionEnvelope:
        ...

    def get_execution(
        self,
        execution_id: str,
    ) -> EfataExecutionEnvelope:
        ...

    def stream_execution(
        self,
        execution_id: str,
    ) -> Iterable[EfataStreamEvent]:
        ...

    def cancel_execution(
        self,
        execution_id: str,
    ) -> EfataExecutionEnvelope:
        ...

    def submit_feedback(
        self,
        execution_id: str,
        feedback: dict,
    ) -> None:
        ...
