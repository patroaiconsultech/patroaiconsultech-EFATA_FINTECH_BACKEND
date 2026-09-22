from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.integrations.efata.platform_v2_client import EfataPlatformV2Client

CONFIRMATION = "PUBLISH_EFATA_MASTER_PLAN"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Governed uploader for the Efatà Fintech Master Plan."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--title", default="Efatà Fintech — Master Plan Comercial")
    parser.add_argument("--scope", default="INSTITUTIONAL")
    parser.add_argument("--classification", default="internal")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = args.file.resolve()
    preview = {
        "mode": "apply" if args.apply else "preview",
        "file": str(path),
        "scope": args.scope,
        "classification": args.classification,
        "allowed_purposes": ["chat", "team", "realtime"],
        "publish_after_upload": bool(args.publish),
        "network_write_executed": False,
    }

    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    if args.confirm != CONFIRMATION:
        raise SystemExit(
            f"Explicit confirmation required: --confirm {CONFIRMATION}"
        )

    settings = get_settings()
    with EfataPlatformV2Client.from_settings(settings) as client:
        document = client.upload_knowledge(
            file_path=path,
            scope=args.scope,
            title=args.title,
            classification=args.classification,
            allowed_purposes=("chat", "team", "realtime"),
        )
        published = None
        if args.publish:
            published = client.publish_knowledge(document_id=document.id)

    result = {
        **preview,
        "network_write_executed": True,
        "uploaded": document.model_dump(mode="json"),
        "published": published.model_dump(mode="json") if published else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
