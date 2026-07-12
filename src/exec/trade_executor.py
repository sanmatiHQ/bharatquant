"""
DEPRECATED — legacy 09:20 manual batch executor (fake sizing, optional missing LTP).

All trading is event-driven via src.engine.main + ExecutionEngine.
Real prices only from Kite TICK/OHLC — fail loud if missing.
"""
from __future__ import annotations

import sys

from ..data.data_policy import reject_legacy_entrypoint
from ..utils.logging_setup import get_logger

logger = get_logger("trading", logs_dir=__import__("os").getenv("LOGS_DIR", "logs"))


def main() -> None:
    logger.error("trade_executor_deprecated")
    reject_legacy_entrypoint(
        "src.exec.trade_executor",
        "python3.11 -m src.engine.main",
    )


if __name__ == "__main__":
    main()
