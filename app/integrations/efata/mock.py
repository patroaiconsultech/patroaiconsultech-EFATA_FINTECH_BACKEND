from uuid import uuid4

from app.integrations.efata.contracts import (
    EfataExecutionEnvelope,
    EfataExecutionRequest,
    EfataStreamEvent,
)


class MockEfataAdapter:
    def __init__(self):
        self._executions: dict[str, EfataExecutionEnvelope] = {}

    def list_capabilities(self) -> list[dict]:
        return [
            {
                "capability_id": "mock.document_preliminary_analysis",
                "status": "mock",
                "version": "r4",
            }
        ]

    def submit_execution(
        self,
        request: EfataExecutionRequest,
    ) -> EfataExecutionEnvelope:
        execution_id = str(uuid4())
        envelope = EfataExecutionEnvelope(
            message_id=str(uuid4()),
            request_id=request.request_id,
            execution_id=execution_id,
            correlation_id=request.correlation_id,
            tenant_id=request.tenant_id,
            capability_id=request.capability_id,
            status="completed",
            content={
                "mode": "mock",
                "purpose": request.purpose,
                "memory_persisted": False,
                "write_executed": False,
            },
        )
        self._executions[execution_id] = envelope
        return envelope

    def get_execution(
        self,
        execution_id: str,
    ) -> EfataExecutionEnvelope:
        return self._executions[execution_id]

    def stream_execution(self, execution_id: str):
        yield EfataStreamEvent(
            event="agent_done",
            execution_id=execution_id,
            sequence=1,
            payload={"status": "completed"},
        )
        yield EfataStreamEvent(
            event="done",
            execution_id=execution_id,
            sequence=2,
            payload={"terminal": True},
        )

    def cancel_execution(
        self,
        execution_id: str,
    ) -> EfataExecutionEnvelope:
        current = self._executions[execution_id]
        cancelled = current.model_copy(update={"status": "cancelled"})
        self._executions[execution_id] = cancelled
        return cancelled

    def submit_feedback(
        self,
        execution_id: str,
        feedback: dict,
    ) -> None:
        if execution_id not in self._executions:
            raise KeyError(execution_id)
