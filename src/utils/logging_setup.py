"""
Structured JSON logging — non-blocking via QueueHandler.
"""
from __future__ import annotations
import json
import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from typing import Any

_LISTENER: QueueListener | None = None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
        }
        standard_keys = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
            "relativeCreated", "thread", "threadName", "processName", "process", "asctime",
        }
        for key, value in record.__dict__.items():
            if key not in standard_keys and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str, logs_dir: str | None = None) -> logging.Logger:
    """Return logger with async QueueHandler + JSON formatting."""
    global _LISTENER
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = JsonFormatter()

    use_async = os.getenv("ASYNC_LOGGING", "true").lower() in ("1", "true", "yes")
    if use_async:
        log_queue: queue.Queue = queue.Queue(-1)
        queue_handler = QueueHandler(log_queue)
        logger.addHandler(queue_handler)

        handlers: list[logging.Handler] = []
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)
        if logs_dir:
            os.makedirs(logs_dir, exist_ok=True)
            file_path = os.path.join(logs_dir, f"{name.split('.')[-1]}.log")
            file_handler = RotatingFileHandler(file_path, maxBytes=2_000_000, backupCount=3)
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        if _LISTENER is None:
            _LISTENER = QueueListener(log_queue, *handlers, respect_handler_level=True)
            _LISTENER.start()
    else:
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
