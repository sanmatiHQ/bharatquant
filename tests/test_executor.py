"""Legacy trade_executor removed — execution is event-driven."""
from __future__ import annotations

import subprocess
import sys


def test_trade_executor_deprecated():
    r = subprocess.run(
        [sys.executable, "-m", "src.exec.trade_executor"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "DEPRECATED" in r.stderr + r.stdout
