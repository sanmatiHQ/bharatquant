"""Optional Gemini news research — never on execution path."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("bharatquant.research.gemini")


def gemini_enabled() -> bool:
    return os.getenv("LLM_ENABLED", "false").lower() in ("1", "true", "yes")


async def summarize_news_headlines(headlines: list[str], symbol: str = "") -> Optional[dict[str, Any]]:
    if not gemini_enabled():
        return None
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("gemini_skipped_no_key")
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
        prompt = (
            f"Summarize market sentiment for {symbol or 'NSE'} from these headlines. "
            "Return JSON: sentiment (bullish|bearish|neutral), bullets (max 3). "
            "Do not recommend trades.\n\n"
            + "\n".join(headlines[:10])
        )
        resp = await model.generate_content_async(prompt)
        text = (resp.text or "").strip()
        return {"symbol": symbol, "summary": text, "source": "gemini", "execution_allowed": False}
    except Exception:
        logger.exception("gemini_summarize_failed")
        return None
