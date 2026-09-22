from pathlib import Path

from app.config import Settings
from app.integrations.efata.platform_v2_client import EfataPlatformV2Client


def test_knowledge_lifecycle_client_contract():
    states = {"status": "DRAFT"}

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if request.method == "POST" and path == "/api/v2/knowledge":
            return httpx.Response(
                200,
                json={
                    "id": "canary-1",
                    "logical_document_id": "logical-1",
                    "version": 1,
                    "scope": "INSTITUTIONAL",
                    "title": "EFATA_FINTECH_KNOWLEDGE_CANARY_001",
                    "filename": "canary.md",
                    "classification": "internal",
                    "status": states["status"],
                    "allowed_purposes": ["chat", "team", "realtime"],
                },
            )

        if request.method == "GET" and path == "/api/v2/knowledge":
            return httpx.Response(
                200,
                json={
                    "items": [{
                        "id": "canary-1",
                        "logical_document_id": "logical-1",
                        "version": 1,
                        "scope": "INSTITUTIONAL",
                        "title": "EFATA_FINTECH_KNOWLEDGE_CANARY_001",
                        "filename": "canary.md",
                        "classification": "internal",
                        "status": states["status"],
                        "allowed_purposes": ["chat", "team", "realtime"],
                    }],
                    "total": 1,
                },
            )

        if request.method == "GET" and path == "/api/v2/knowledge/canary-1/content":
            return httpx.Response(
                200,
                json={
                    "knowledge_id": "canary-1",
                    "sections": [{
                        "section_id": "section-1",
                        "heading": None,
                        "content": "CANARY_MARKER=EFATA_FINTECH_KNOWLEDGE_CANARY_001_9F33D7",
                    }],
                    "provided_chars": 60,
                    "truncated": False,
                },
            )

        if request.method == "POST" and path == "/api/v2/knowledge/canary-1/publish":
            states["status"] = "ACTIVE"
        elif request.method == "POST" and path == "/api/v2/knowledge/canary-1/revoke":
            states["status"] = "REVOKED"
        elif request.method == "DELETE" and path == "/api/v2/knowledge/canary-1":
            return httpx.Response(200, json={"status": "deleted", "id": "canary-1"})
        else:
            return httpx.Response(404)

        return httpx.Response(
            200,
            json={
                "id": "canary-1",
                "logical_document_id": "logical-1",
                "version": 1,
                "scope": "INSTITUTIONAL",
                "title": "EFATA_FINTECH_KNOWLEDGE_CANARY_001",
                "filename": "canary.md",
                "classification": "internal",
                "status": states["status"],
                "allowed_purposes": ["chat", "team", "realtime"],
            },
        )

    canary = Path(__file__).resolve().parents[2] / "KNOWLEDGE" / "EFATA_FINTECH_KNOWLEDGE_CANARY_001.md"
    # Unit-test fixture uses a tiny temporary file because the actual canary
    # lives at package root, outside backend.
    tmp = Path(__file__).with_name("_canary_test.md")
    tmp.write_text(
        "CANARY_MARKER=EFATA_FINTECH_KNOWLEDGE_CANARY_001_9F33D7",
        encoding="utf-8",
    )
    try:
        with EfataPlatformV2Client(
            base_url="https://efata.example",
            access_token="token",
            transport=httpx.MockTransport(handler),
        ) as client:
            uploaded = client.upload_knowledge(
                file_path=tmp,
                title="EFATA_FINTECH_KNOWLEDGE_CANARY_001",
            )
            assert uploaded.status == "DRAFT"
            assert client.list_knowledge()[0].id == "canary-1"
            content = client.get_knowledge_content(document_id="canary-1")
            assert "CANARY_MARKER" in content["sections"][0]["content"]
            assert client.publish_knowledge(document_id="canary-1").status == "ACTIVE"
            assert client.revoke_knowledge(document_id="canary-1").status == "REVOKED"
    finally:
        tmp.unlink(missing_ok=True)
