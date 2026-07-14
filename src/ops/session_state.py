"""Exchange session state — authoritative gate for new entries (not wall-clock alone)."""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger("bharatquant.session_state")

SessionPhase = Literal["UNKNOWN", "PRE_OPEN", "OPEN", "CLOSED"]

_phase: SessionPhase = "UNKNOWN"


def set_session_phase(phase: SessionPhase) -> None:
    global _phase
    if phase != _phase:
        logger.info("session_phase", extra={"from": _phase, "to": phase})
    _phase = phase


def session_phase() -> SessionPhase:
    return _phase


def entries_allowed(*, allow_exits: bool = True) -> bool:
    """New BUY entries only when exchange session is OPEN."""
    return _phase == "OPEN"


def normalize_nse_status(raw: str) -> SessionPhase:
    s = raw.strip().lower().replace("_", "-").replace(" ", "-")
    if "pre" in s and "open" in s:
        return "PRE_OPEN"
    if s in ("open", "normal-market-open", "normal-market"):
        return "OPEN"
    if "close" in s or s in ("closed", "close"):
        return "CLOSED"
    return "UNKNOWN"
