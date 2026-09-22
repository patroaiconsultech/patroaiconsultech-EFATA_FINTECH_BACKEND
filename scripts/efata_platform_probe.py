from __future__ import annotations

import json

from app.config import get_settings
from app.integrations.efata.platform_v2_client import EfataPlatformV2Client


def main() -> int:
    settings = get_settings()
    with EfataPlatformV2Client.from_settings(settings) as client:
        snapshot = client.probe()
    print(snapshot.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
