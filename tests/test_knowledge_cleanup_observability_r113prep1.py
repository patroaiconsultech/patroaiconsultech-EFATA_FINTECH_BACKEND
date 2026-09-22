from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.integrations.efata.platform_v2_client import EfataV2BridgeError


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "efata_knowledge_canary.py"
SPEC = importlib.util.spec_from_file_location("efata_knowledge_canary", SCRIPT)
assert SPEC and SPEC.loader
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


class FailingClient:
    def delete_knowledge_draft(self, *, document_id: str):
        raise EfataV2BridgeError(
            "UPSTREAM_UNAVAILABLE",
            "must not expose upstream body",
        )


class SuccessClient:
    def delete_knowledge_draft(self, *, document_id: str):
        return {"status": "deleted", "id": document_id}


def test_cleanup_failure_is_visible_and_traceable(capsys):
    with pytest.raises(RuntimeError) as captured:
        canary.cleanup_draft_with_evidence(
            client=FailingClient(),
            document_id="doc-canary-123",
        )

    assert "CLEANUP_FAILED document_id=doc-canary-123" in str(captured.value)
    stderr = capsys.readouterr().err
    payload = json.loads(stderr.strip())
    assert payload["event"] == "CLEANUP_FAILED"
    assert payload["document_id"] == "doc-canary-123"
    assert payload["error_code"] == "UPSTREAM_UNAVAILABLE"
    assert "remediation" in payload


def test_cleanup_success_returns_evidence():
    result = canary.cleanup_draft_with_evidence(
        client=SuccessClient(),
        document_id="doc-canary-456",
    )
    assert result["event"] == "CLEANUP_SUCCEEDED"
    assert result["document_id"] == "doc-canary-456"
