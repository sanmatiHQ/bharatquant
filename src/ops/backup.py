"""SQLite backup to GCS on SESSION_CLOSE — BQ-15."""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from .gcs_store import upload_file

logger = logging.getLogger("bharatquant.backup")


def backup_sqlite(sqlite_path: str, *, bucket: str | None = None) -> bool:
    bucket = bucket or os.getenv("GCS_BACKUP_BUCKET", "")
    if not bucket:
        logger.info("backup_skipped", extra={"reason": "GCS_BACKUP_BUCKET unset"})
        return False
    src = Path(sqlite_path)
    if not src.exists():
        logger.warning("backup_missing_db", extra={"path": str(src)})
        return False
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = src.parent / f"trading_{stamp}.db"
    shutil.copy2(src, dest)
    key = f"backups/trading_{stamp}.db"
    ok = upload_file(dest, key, bucket=bucket)
    dest.unlink(missing_ok=True)
    return ok
