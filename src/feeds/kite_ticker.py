"""Kite WebSocket → EventBus TICK events. Docs: https://kite.trade/docs/pykiteconnect/v4/"""
from __future__ import annotations

import logging
import os
from typing import Callable, List, Optional

from kiteconnect import KiteTicker

from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.kite_ticker")


class KiteTickFeed:
    def __init__(
        self,
        api_key: str,
        access_token: str,
        on_event: Callable[[MarketEvent], None],
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._on_event = on_event
        self._kws: Optional[KiteTicker] = None
        self._token_to_symbol: dict[int, str] = {}

    def _handle_ticks(self, ws: KiteTicker, ticks: list) -> None:
        for t in ticks:
            token = t.get("instrument_token")
            symbol = self._token_to_symbol.get(token, str(token))
            price = float(t.get("last_price") or 0)
            if price <= 0:
                continue
            self._on_event(
                MarketEvent(
                    type=EventType.TICK,
                    symbol=symbol,
                    price=price,
                    payload={"raw": t},
                )
            )

    def _handle_order_update(self, ws: KiteTicker, data: dict) -> None:
        status = str(data.get("status", "")).upper()
        if status not in ("COMPLETE", "FILLED"):
            return
        sym = str(data.get("tradingsymbol", ""))
        self._on_event(
            MarketEvent(
                type=EventType.ORDER_FILL,
                symbol=sym,
                price=float(data.get("average_price", data.get("price", 0)) or 0),
                payload={
                    "order_id": str(data.get("order_id", "")),
                    "symbol": sym,
                    "side": str(data.get("transaction_type", "BUY")),
                    "qty": int(data.get("filled_quantity", data.get("quantity", 0)) or 0),
                    "fill_price": float(data.get("average_price", 0) or 0),
                    "status": status,
                },
            )
        )

    def _handle_connect(self, ws: KiteTicker, response) -> None:
        tokens = list(self._token_to_symbol.keys())
        if tokens:
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_QUOTE, tokens)
        logger.info("kite_ws_connected", extra={"subscribed": len(tokens)})

    def start(self, token_symbol_map: dict[int, str]) -> None:
        self._token_to_symbol = token_symbol_map
        self._kws = KiteTicker(self._api_key, self._access_token)
        self._kws.on_ticks = self._handle_ticks
        self._kws.on_connect = self._handle_connect
        self._kws.on_close = self._handle_close
        self._kws.on_error = self._handle_error
        self._kws.on_order_update = self._handle_order_update
        self._kws.connect(threaded=True)

    def _handle_close(self, ws, code, reason) -> None:
        logger.warning("kite_ws_closed", extra={"code": code, "reason": reason})

    def _handle_error(self, ws, code, reason) -> None:
        logger.error("kite_ws_error", extra={"code": code, "reason": reason})
        if code in (403, 401, 1006):
            self._on_event(
                MarketEvent(type=EventType.WS_AUTH_FAIL, payload={"code": code, "reason": str(reason)})
            )

    def stop(self) -> None:
        if self._kws:
            self._kws.close()


def load_access_token(path: str | None = None) -> tuple[str, str]:
    import json
    from pathlib import Path

    api_key = os.environ["KITE_API_KEY"]
    token_path = Path(path or os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json"))
    data = json.loads(token_path.read_text(encoding="utf-8"))
    token = data.get("access_token") or (data.get("data") or {}).get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in {token_path}")
    return api_key, str(token)
