"""
Tier 1 LLM Brain — hourly macro bias (-1..+1).
On ANY failure → llm_bias = 0.0 (conservative fallback).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Callable, Optional

import httpx

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.llm_macro")

KEY_LLM_BIAS = "llm_macro_bias"
KEY_LLM_TS = "llm_macro_updated_ts"
KEY_LLM_DETAIL = "llm_macro_detail"


def llm_enabled() -> bool:
    return os.getenv("LLM_ENABLED", "false").lower() in ("1", "true", "yes")


def get_stored_bias(db) -> float:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_LLM_BIAS,)).fetchone()
    return float(row["v"]) if row and row["v"] else 0.0


def _persist_bias(db, bias: float, detail: dict) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_LLM_BIAS, str(round(bias, 4))),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_LLM_TS, str(int(time.time()))),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_LLM_DETAIL, json.dumps(detail)),
        )


def _build_prompt(ctx: dict) -> str:
    return (
        "You are a macro analyst for Indian NSE equities. "
        "Given the data below, output ONLY valid JSON with keys: "
        "bias (float -1.0 bearish to +1.0 bullish), "
        "sectors (object mapping sector name to bias -1..+1), "
        "summary (max 2 sentences). "
        "Do not recommend specific trades.\n\n"
        f"FII net (cr): {ctx.get('fii_net_cr', 0)}\n"
        f"DII net (cr): {ctx.get('dii_net_cr', 0)}\n"
        f"GIFT Nifty %: {ctx.get('gift_pct', 0)}\n"
        f"India VIX: {ctx.get('india_vix', 0)}\n"
        f"US futures %: {ctx.get('us_sp', 0)}\n"
        f"Crude %: {ctx.get('crude', 0)}\n"
        f"USDINR %: {ctx.get('usd_inr', 0)}\n"
        f"Futures OI chg %: {ctx.get('futures_oi_chg', 0)}\n"
        f"Headlines: {ctx.get('headlines', [])}\n"
    )


def _parse_bias(text: str) -> tuple[float, dict]:
    """Extract bias from LLM response; default 0.0 on parse failure."""
    detail: dict = {"raw": text[:500]}
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        m = re.search(r"\{[^{}]*\"bias\"[^{}]*\}", cleaned, re.DOTALL)
        if m:
            obj = json.loads(m.group())
        else:
            obj = json.loads(cleaned)
        bias = float(obj.get("bias", 0))
        detail = obj
        return max(-1.0, min(1.0, bias)), detail
    except Exception:
        logger.warning("llm_bias_parse_failed", extra={"snippet": text[:200]})
        return 0.0, detail


async def _metadata_access_token() -> Optional[str]:
    """GCP VM default service account token (Vertex AI billing)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
            )
            r.raise_for_status()
            return str(r.json()["access_token"])
    except Exception:
        return None


def _vertex_enabled() -> bool:
    if os.getenv("VERTEX_GEMINI_ENABLED", "true").lower() in ("0", "false", "no"):
        return False
    return bool(os.getenv("GCP_PROJECT") or os.getenv("GCP_PROJECT_ID"))


async def _call_vertex_gemini(prompt: str) -> Optional[str]:
    """Gemini via Vertex AI — uses VM service account (GCP billing, no AI Studio credits)."""
    if not _vertex_enabled():
        return None
    project = os.getenv("GCP_PROJECT") or os.getenv("GCP_PROJECT_ID", "")
    location = os.getenv("VERTEX_LOCATION", "us-central1")
    model = os.getenv("VERTEX_GEMINI_MODEL", "gemini-2.5-flash")
    if not project:
        return None
    token = await _metadata_access_token()
    if not token:
        return None
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/publishers/google/models/{model}:generateContent"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
            )
            r.raise_for_status()
            data = r.json()
            parts = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            if parts and parts[0].get("text"):
                return str(parts[0]["text"]).strip()
    except Exception:
        logger.exception("vertex_gemini_macro_failed")
    return None


async def _call_gemini(prompt: str) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
        resp = await model.generate_content_async(prompt)
        return (resp.text or "").strip()
    except Exception:
        logger.exception("gemini_macro_failed")
        return None


async def _call_openai_compat(prompt: str) -> Optional[str]:
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    model = os.getenv("LLM_MODEL_NAME", "gpt-4o")
    if not base or not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("openai_compat_macro_failed")
        return None


async def _call_anthropic(prompt: str) -> Optional[str]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            blocks = data.get("content") or []
            if blocks and blocks[0].get("text"):
                return str(blocks[0]["text"]).strip()
    except Exception:
        logger.exception("anthropic_macro_failed")
    return None


async def compute_llm_bias(db, ctx: dict) -> float:
    """
    Tier 1 brain — returns bias in [-1, +1].
    ALWAYS returns 0.0 on disabled LLM, timeout, or parse error.
    """
    if not llm_enabled():
        _persist_bias(db, 0.0, {"source": "disabled", "bias": 0.0})
        return 0.0
    try:
        prompt = _build_prompt(ctx)
        text = await _call_vertex_gemini(prompt)
        source = "vertex_gemini"
        if not text:
            text = await _call_gemini(prompt)
            source = "gemini"
        if not text:
            text = await _call_openai_compat(prompt)
            source = "openai"
        if not text:
            text = await _call_anthropic(prompt)
            source = "anthropic"
        if not text:
            _persist_bias(db, 0.0, {"source": "api_unavailable", "bias": 0.0})
            return 0.0
        bias, detail = _parse_bias(text)
        detail["source"] = detail.get("source", source)
        _persist_bias(db, bias, detail)
        return bias
    except Exception:
        logger.exception("llm_macro_compute_failed")
        _persist_bias(db, 0.0, {"source": "exception", "bias": 0.0})
        return 0.0


async def poll_llm_macro(publish: Callable, db, interval_sec: float | None = None) -> None:
    """Hourly LLM macro loop — publishes LLM_BIAS_UPDATE."""
    sec = interval_sec or float(os.getenv("LLM_MACRO_INTERVAL_SEC", "3600"))
    while True:
        try:
            from ..ops.agent_state import _get

            ctx_raw = _get(db, "agent_context")
            ctx = json.loads(ctx_raw) if ctx_raw else {}
            headlines_row = db._conn.execute(
                "SELECT payload_json FROM ingest_log ORDER BY ts DESC LIMIT 8"
            ).fetchall()
            headlines = []
            for r in headlines_row:
                try:
                    p = json.loads(r["payload_json"])
                    headlines.append(str(p.get("title", p.get("summary", "")))[:120])
                except Exception:
                    pass
            ctx["headlines"] = headlines
            oi_row = db._conn.execute(
                "SELECT oi_change_pct FROM futures_oi ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            ctx["futures_oi_chg"] = float(oi_row["oi_change_pct"]) if oi_row else 0.0

            bias = await compute_llm_bias(db, ctx)
            payload = tag_payload(
                {"llm_bias": bias, "llm_sentiment": bias, "updated_ts": int(time.time())},
                source="llm_macro",
                execution_allowed=True,
            )
            await publish(MarketEvent(type=EventType.LLM_BIAS_UPDATE, symbol="MACRO", payload=payload))
            with db.tx() as conn:
                record_ingest(conn, source="llm_macro", event_type=EventType.LLM_BIAS_UPDATE, payload=payload, execution_allowed=True)
            logger.info("llm_macro_published", extra={"bias": bias})
        except Exception:
            logger.exception("llm_macro_poll_error")
            try:
                _persist_bias(db, 0.0, {"source": "poll_exception", "bias": 0.0})
            except Exception:
                pass
        await asyncio.sleep(sec)
