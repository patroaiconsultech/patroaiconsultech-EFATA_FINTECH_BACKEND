from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.integrations.efata.platform_v2_client import (
    EfataPlatformV2Client,
    EfataV2BridgeError,
)

DRAFT_CONFIRMATION = "UPLOAD_DELETE_EFATA_KNOWLEDGE_CANARY"
LIFECYCLE_CONFIRMATION = "PUBLISH_REVOKE_EFATA_KNOWLEDGE_CANARY"
CLEANUP_REMEDIATION = (
    "Remove the orphan DRAFT manually from the authorized Efatà tenant after "
    "verifying the document_id, then attach the remediation evidence to the gate."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthetic Knowledge Plane canary. Preview-only by default."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--mode",
        choices=("preview", "draft-cleanup", "lifecycle"),
        default="preview",
    )
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def _canonical_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        str(section.get("content") or "")
        for section in payload.get("sections", [])
    ).strip()


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, EfataV2BridgeError):
        return exc.code
    return type(exc).__name__


def cleanup_draft_with_evidence(
    *,
    client: EfataPlatformV2Client,
    document_id: str,
) -> dict[str, Any]:
    """Attempt DRAFT cleanup and always return/raise structured evidence.

    No token, Authorization header or response body is recorded.
    """
    try:
        cleanup = client.delete_knowledge_draft(document_id=document_id)
    except Exception as exc:
        evidence = {
            "event": "CLEANUP_FAILED",
            "document_id": document_id,
            "error_code": _safe_error_code(exc),
            "remediation": CLEANUP_REMEDIATION,
        }
        # stderr makes orphan evidence visible even when another exception is
        # already propagating. This is intentionally not swallowed.
        print(json.dumps(evidence, ensure_ascii=False), file=sys.stderr)
        raise RuntimeError(
            f"CLEANUP_FAILED document_id={document_id}"
        ) from exc

    return {
        "event": "CLEANUP_SUCCEEDED",
        "document_id": document_id,
        "cleanup": cleanup,
    }


def main() -> int:
    args = parse_args()
    path = args.file.resolve()
    source = path.read_text(encoding="utf-8").strip()
    marker = "EFATA_FINTECH_KNOWLEDGE_CANARY_001_9F33D7"
    if marker not in source:
        raise SystemExit("Synthetic canary marker missing.")

    preview = {
        "mode": args.mode,
        "file": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "scope": "INSTITUTIONAL",
        "classification": "internal",
        "allowed_purposes": ["chat", "team", "realtime"],
        "contains_real_data": False,
        "network_write_executed": False,
    }
    if args.mode == "preview":
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return 0

    expected = (
        DRAFT_CONFIRMATION
        if args.mode == "draft-cleanup"
        else LIFECYCLE_CONFIRMATION
    )
    if args.confirm != expected:
        raise SystemExit(f"Explicit confirmation required: --confirm {expected}")

    settings = get_settings()
    result = dict(preview)
    uploaded_id: str | None = None
    operation_error: Exception | None = None

    with EfataPlatformV2Client.from_settings(settings) as client:
        try:
            uploaded = client.upload_knowledge(
                file_path=path,
                scope="INSTITUTIONAL",
                title="EFATA_FINTECH_KNOWLEDGE_CANARY_001",
                classification="internal",
                allowed_purposes=("chat", "team", "realtime"),
            )
            uploaded_id = uploaded.id
            if uploaded.status != "DRAFT":
                raise RuntimeError("CANARY_UPLOAD_MUST_START_DRAFT")

            listed = client.list_knowledge(scope="INSTITUTIONAL")
            listed_row = next(
                (item for item in listed if item.id == uploaded.id),
                None,
            )
            if listed_row is None:
                raise RuntimeError("CANARY_NOT_VISIBLE_IN_INSTITUTIONAL_SCOPE")
            if listed_row.allowed_purposes != ["chat", "team", "realtime"]:
                raise RuntimeError("CANARY_PURPOSES_MISMATCH")

            content = client.get_knowledge_content(document_id=uploaded.id)
            roundtrip = _canonical_text(content)
            if marker not in roundtrip:
                raise RuntimeError("CANARY_CONTENT_MARKER_MISSING")

            if args.mode == "draft-cleanup":
                cleanup_evidence = cleanup_draft_with_evidence(
                    client=client,
                    document_id=uploaded.id,
                )
                result.update(
                    {
                        "network_write_executed": True,
                        "uploaded_id": uploaded.id,
                        "content_marker_verified": True,
                        "cleanup": cleanup_evidence,
                    }
                )
                uploaded_id = None
            else:
                active = client.publish_knowledge(document_id=uploaded.id)
                if active.status != "ACTIVE":
                    raise RuntimeError("CANARY_PUBLISH_DID_NOT_ACTIVATE")
                revoked = client.revoke_knowledge(document_id=uploaded.id)
                if revoked.status != "REVOKED":
                    raise RuntimeError("CANARY_REVOKE_DID_NOT_REVOKE")
                result.update(
                    {
                        "network_write_executed": True,
                        "uploaded_id": uploaded.id,
                        "content_marker_verified": True,
                        "active_status": active.status,
                        "revoked_status": revoked.status,
                        "runtime_retrieval_exclusion_proven": False,
                        "runtime_retrieval_exclusion_note": (
                            "Requires a separately authorized chat/team/realtime "
                            "retrieval canary after R11.3B."
                        ),
                    }
                )
                # ACTIVE/REVOKED is never silently deleted.
                uploaded_id = None
        except Exception as exc:
            operation_error = exc
            raise
        finally:
            # Only a DRAFT can receive best-effort cleanup here. If cleanup
            # itself fails, evidence is printed with document_id/remediation.
            # If another operation error is already propagating, preserve it
            # while leaving the CLEANUP_FAILED evidence visible on stderr.
            if uploaded_id is not None and args.mode == "draft-cleanup":
                try:
                    cleanup_draft_with_evidence(
                        client=client,
                        document_id=uploaded_id,
                    )
                    uploaded_id = None
                except Exception:
                    if operation_error is None:
                        raise

        result["observations"] = [
            item.model_dump(mode="json")
            for item in client.observations
        ]

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
