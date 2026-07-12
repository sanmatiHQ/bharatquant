"""
Data integrity policy — no fake OHLC, no silent fallbacks on execution path.

Old project failures this blocks:
  - ltp=100 hardcoded fallback
  - dummy OHLC in screener
  - manual 09:20 cron with placeholder sizing
  - Flask stub endpoints returning empty gainers/losers
  - RL transitions with zero reward placeholders
"""
from __future__ import annotations


class DataIntegrityError(RuntimeError):
    """Raised when required live data is missing — never substitute defaults."""


def require_positive_price(price: float, context: str) -> float:
    if price is None or price <= 0:
        raise DataIntegrityError(f"Missing or invalid price for {context}: {price!r}")
    return float(price)


def require_kite_feed(feed) -> None:
    if feed is None:
        raise DataIntegrityError(
            "KiteDataFeed unavailable — set KITE_API_KEY and .kite_token.json. "
            "No manual CSV OHLC or fake LTP permitted."
        )


def reject_legacy_entrypoint(name: str, replacement: str) -> None:
    raise SystemExit(
        f"DEPRECATED: {name} uses old manual/fake-data flows. "
        f"Use: {replacement}"
    )
