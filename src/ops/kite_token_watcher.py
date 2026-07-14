"""Hot-reload Kite WebSocket when OAuth saves a new token — no full engine restart."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger("bharatquant.kite_token_watcher")


async def watch_kite_token_file(
    restart_feed: Callable[[], None],
    *,
    interval_sec: float = 10.0,
) -> None:
    """Detect token file mtime change → validate live → restart KiteTickFeed."""
    path = Path(os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json"))
    last_mtime = path.stat().st_mtime if path.exists() else 0.0

    while True:
        await asyncio.sleep(interval_sec)
        try:
            if not path.exists():
                continue
            mtime = path.stat().st_mtime
            if mtime <= last_mtime + 0.001:
                continue
            last_mtime = mtime
            from .healthchecks import check_token, invalidate_token_cache

            invalidate_token_cache()
            if not check_token(live=True):
                logger.warning("kite_token_file_changed_but_invalid")
                continue
            logger.info("kite_token_file_updated", extra={"action": "restart_feed"})
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(restart_feed)
        except Exception:
            logger.exception("kite_token_watch_error")
