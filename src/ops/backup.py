"""SQLite backup to GCS on SESSION_CLOSE — BQ-15."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

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
    uri = f"gs://{bucket.rstrip('/')}/backups/trading_{stamp}.db"
    try:
        subprocess.run(
            ["gcloud", "storage", "cp", str(dest), uri],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        dest.unlink(missing_ok=True)
        logger.info("backup_ok", extra={"uri": uri})
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("backup_failed", extra={"error": str(exc), "local": str(dest)})
        return False
