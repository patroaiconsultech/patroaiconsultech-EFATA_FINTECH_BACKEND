import json
import logging
from datetime import datetime, timezone

from app.config import get_settings


class JsonFormatter(logging.Formatter):
    SAFE_FIELDS = (
        "request_id",
        "correlation_id",
        "tenant_id",
        "user_id",
        "auth_provider",
        "event_code",
        "method",
        "path",
        "status_code",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.SAFE_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
