"""
Structured JSON logging setup.
"""
from __future__ import annotations
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
        }
        # Include any extra attributes added via logger.info(..., extra={...})
        standard_keys = {
            'name','msg','args','levelname','levelno','pathname','filename','module','exc_info','exc_text','stack_info',
            'lineno','funcName','created','msecs','relativeCreated','thread','threadName','processName','process','asctime'
        }
        for key, value in record.__dict__.items():
            if key not in standard_keys and not key.startswith('_'):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str, logs_dir: str | None = None) -> logging.Logger:
    """Return a logger writing JSON to stdout and optional file in logs_dir."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    formatter = JsonFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if logs_dir:
        os.makedirs(logs_dir, exist_ok=True)
        file_path = os.path.join(logs_dir, f"{name.split('.')[-1]}.log")
        file_handler = RotatingFileHandler(file_path, maxBytes=2_000_000, backupCount=3)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
