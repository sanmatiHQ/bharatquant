"""Single source for TRADING_MODE — env overrides config.yaml."""
from __future__ import annotations

import os
from pathlib import Path

_VALID = frozenset({"paper", "live"})


def resolved_trading_mode() -> str:
    env = os.getenv("TRADING_MODE", "").strip().lower()
    if env in _VALID:
        return env
    yaml_mode = _mode_from_yaml()
    if yaml_mode in _VALID:
        return yaml_mode
    return "paper"


def _mode_from_yaml() -> str:
    path = Path(os.getenv("BHARATQUANT_CONFIG", "config.yaml"))
    if not path.is_file():
        return "paper"
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return str((data.get("trading") or {}).get("mode", "paper")).strip().lower()
    except Exception:
        return "paper"
