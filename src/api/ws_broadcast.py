"""WebSocket + SSE broadcast manager for live dashboard telemetry."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("bharatquant.ws_broadcast")


class FeedConnectionManager:
    def __init__(self) -> None:
        self._websockets: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._websockets.append(websocket)

    async def disconnect_ws(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._websockets:
                self._websockets.remove(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, default=str)
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._websockets:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in self._websockets:
                    self._websockets.remove(ws)

    @property
    def ws_count(self) -> int:
        return len(self._websockets)


feed_manager = FeedConnectionManager()
