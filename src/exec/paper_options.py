"""Paper options broker — simulated NFO fills for learning (no live margin)."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..db.database import DB


@dataclass
class PaperOptionsBroker:
    slippage_bps: int = 8

    def _slip(self, price: float, side: str) -> float:
        bps = self.slippage_bps / 10_000.0
        return price * (1 + bps) if side.upper() == "BUY" else price * (1 - bps)

    def buy(
        self,
        db: DB,
        *,
        underlying: str,
        strike: float,
        option_type: str,
        qty: int,
        ltp: float,
        expiry: str,
        reason: str,
    ) -> dict:
        sym = f"{underlying}:{expiry}:{int(strike)}{option_type[0].upper()}"
        px = self._slip(ltp, "BUY")
        ts = int(time.time())
        premium = px * qty
        with db.tx() as conn:
            row = conn.execute(
                "SELECT qty, avg_premium FROM option_positions WHERE symbol=?", (sym,)
            ).fetchone()
            if row:
                old_q = int(row["qty"])
                old_avg = float(row["avg_premium"])
                new_q = old_q + qty
                new_avg = (old_avg * old_q + px * qty) / new_q
                conn.execute(
                    """
                    UPDATE option_positions SET qty=?, avg_premium=?, last_premium=?, reason=?
                    WHERE symbol=?
                    """,
                    (new_q, new_avg, px, reason, sym),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO option_positions(symbol, underlying, strike, option_type, expiry, qty, avg_premium, last_premium, open_ts, reason)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (sym, underlying, strike, option_type, expiry, qty, px, px, ts, reason),
                )
            conn.execute(
                "INSERT INTO trades(ts, symbol, side, qty, price, amount, reason, fees, stcg_ltcg, order_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts, sym, "BUY", qty, px, premium, reason, 20.0, "NA", f"PAPER-OPT-B-{ts}"),
            )
        db.add_cash(ts, -(premium + 20.0), f"opt_buy:{sym}")
        return {"ok": True, "symbol": sym, "qty": qty, "premium": px, "total": premium + 20}
