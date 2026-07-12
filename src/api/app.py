"""
DEPRECATED — use src.api.dashboard (FastAPI) instead.

Legacy Flask app had stub endpoints (fake market-updates, placeholder PnL).
"""
from __future__ import annotations

import sys

from ..data.data_policy import reject_legacy_entrypoint


def main() -> None:
    reject_legacy_entrypoint(
        "src.api.app (Flask)",
        "python3.11 -m src.api.dashboard",
    )


if __name__ == "__main__":
    main()
