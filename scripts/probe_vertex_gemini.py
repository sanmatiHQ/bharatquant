#!/usr/bin/env python3.11
"""Smoke test Vertex AI Gemini via VM default service account."""
from __future__ import annotations

import json
import os
import sys

import httpx


def _metadata_token() -> str:
    r = httpx.get(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
        timeout=10.0,
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


def main() -> int:
    project = os.getenv("GCP_PROJECT", "your-gcp-project-id")
    location = os.getenv("VERTEX_LOCATION", "asia-south1")
    model = os.getenv("VERTEX_GEMINI_MODEL", "gemini-2.0-flash")
    token = _metadata_token()
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/publishers/google/models/{model}:generateContent"
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": 'Reply ONLY JSON: {"bias": 0.5, "summary": "vertex ok"}'}],
            }
        ]
    }
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=60.0,
    )
    print("status", r.status_code)
    print(r.text[:1200])
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
