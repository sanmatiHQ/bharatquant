"""
DEPRECATED — trading must not use cron (see src/engine/main.py + EventBus).
This module retained only for non-trading ops reference; do not schedule buys/sells here.
"""
from __future__ import annotations

import sys

from ..utils.logging_setup import get_logger

LOGS_DIR = __import__("os").getenv("LOGS_DIR", "logs")
logger = get_logger("scheduler", logs_dir=LOGS_DIR)


def main() -> None:
    logger.error("scheduler_deprecated_use_engine")
    print(
        "ERROR: APScheduler trading jobs removed. Run: python3.11 -m src.engine.main",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
