import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        message = record.getMessage()
        try:
            event = json.loads(message)
        except (ValueError, TypeError):
            event = None
        if isinstance(event, dict):
            payload.update(event)
        else:
            payload["message"] = message
        if record.exc_info:
            # Do not interpolate traceback locals, configuration or exception values.
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
