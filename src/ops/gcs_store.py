"""GCS upload/download — google-cloud-storage with gcloud CLI fallback."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("bharatquant.gcs")


def _bucket() -> str:
    return os.getenv("GCS_BACKUP_BUCKET", "").strip().rstrip("/")


def upload_file(local_path: str | Path, gcs_key: str, *, bucket: str | None = None) -> bool:
    """Upload local file to gs://bucket/gcs_key."""
    b = (bucket or _bucket()).strip()
    if not b:
        logger.info("gcs_upload_skipped", extra={"reason": "GCS_BACKUP_BUCKET unset"})
        return False
    local = Path(local_path)
    if not local.exists():
        logger.warning("gcs_upload_missing", extra={"path": str(local)})
        return False
    uri = f"gs://{b}/{gcs_key.lstrip('/')}"
    try:
        from google.cloud import storage  # type: ignore

        client = storage.Client(project=os.getenv("GCP_PROJECT_ID") or None)
        blob = client.bucket(b).blob(gcs_key.lstrip("/"))
        blob.upload_from_filename(str(local))
        logger.info("gcs_upload_ok", extra={"uri": uri})
        return True
    except Exception as exc:
        logger.info("gcs_upload_fallback_cli", extra={"error": str(exc)[:120]})
        try:
            subprocess.run(
                ["gcloud", "storage", "cp", str(local), uri],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            logger.info("gcs_upload_ok", extra={"uri": uri, "via": "gcloud"})
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as cli_exc:
            logger.warning("gcs_upload_failed", extra={"error": str(cli_exc), "uri": uri})
            return False


def download_file(gcs_key: str, local_path: str | Path, *, bucket: str | None = None) -> bool:
    b = (bucket or _bucket()).strip()
    if not b:
        return False
    local = Path(local_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    uri = f"gs://{b}/{gcs_key.lstrip('/')}"
    try:
        from google.cloud import storage  # type: ignore

        client = storage.Client(project=os.getenv("GCP_PROJECT_ID") or None)
        client.bucket(b).blob(gcs_key.lstrip("/")).download_to_filename(str(local))
        logger.info("gcs_download_ok", extra={"uri": uri})
        return True
    except Exception as exc:
        try:
            subprocess.run(
                ["gcloud", "storage", "cp", uri, str(local)],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("gcs_download_failed", extra={"error": str(exc), "uri": uri})
            return False


def sync_rl_model(model_dir: str, version: str) -> bool:
    """Push local RL weights to GCS models/{version}/."""
    d = Path(model_dir) / version
    policy = d / "policy.npz"
    if not policy.exists():
        return False
    return upload_file(policy, f"models/{version}/policy.npz")


def restore_rl_model(model_dir: str, version: str) -> bool:
    d = Path(model_dir) / version
    d.mkdir(parents=True, exist_ok=True)
    return download_file(f"models/{version}/policy.npz", d / "policy.npz")
