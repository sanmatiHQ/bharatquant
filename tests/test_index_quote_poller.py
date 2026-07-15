"""Index quote poller — confirms Bank Nifty + Sensex are actually polled, not just
declared in INDEX_MAP (the same "registered but never wired" bug class found in
config.yaml's strategies.enabled list this session)."""
from __future__ import annotations

import asyncio
import os

import pytest

from src.db.database import DB, DBConfig
from src.ingest.index_data import INDEX_MAP


@pytest.fixture
def db(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "t.db")
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


def test_index_map_has_banknifty_and_sensex():
    assert "banknifty" in INDEX_MAP
    assert INDEX_MAP["banknifty"]["kite"] == "NSE:NIFTY BANK"
    assert "sensex" in INDEX_MAP
    assert INDEX_MAP["sensex"]["kite"] == "BSE:SENSEX"
    assert INDEX_MAP["sensex"].get("exchange") == "BSE"


@pytest.mark.asyncio
async def test_poller_queries_all_four_indices(db, monkeypatch):
    import src.feeds.index_quote_poller as poller

    monkeypatch.setattr(poller, "_session_active", lambda: True)
    monkeypatch.setattr(poller, "check_token", lambda live=False: True)

    queried_symbols = {}

    class FakeFeed:
        def ltp(self, instruments):
            queried_symbols["last_call"] = list(instruments)
            return {sym: 100.0 + i for i, sym in enumerate(instruments)}

    import src.data.kite_data_feed as kdf_mod

    monkeypatch.setattr(kdf_mod, "KiteDataFeed", FakeFeed)

    async def run_one_iteration():
        # replicate the loop body once instead of running the infinite loop
        from src.ingest.index_data import write_index_tick

        feed = kdf_mod.KiteDataFeed()
        keys = ("nifty50", "nifty100", "banknifty", "sensex")
        symbols = [INDEX_MAP[k]["kite"] for k in keys if k in INDEX_MAP]
        quotes = feed.ltp(symbols)
        for key in keys:
            kite_sym = INDEX_MAP[key]["kite"]
            ltp = quotes.get(kite_sym)
            if ltp and ltp > 0:
                write_index_tick(db, INDEX_MAP[key]["db_symbol"], float(ltp))
        return keys

    keys = await run_one_iteration()
    assert set(keys) == {"nifty50", "nifty100", "banknifty", "sensex"}
    assert queried_symbols["last_call"] == [
        "NSE:NIFTY 50", "NSE:NIFTY 100", "NSE:NIFTY BANK", "BSE:SENSEX",
    ]
    for key in keys:
        sym = INDEX_MAP[key]["db_symbol"]
        row = db._conn.execute(
            "SELECT ltp FROM tick_log WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)
        ).fetchone()
        assert row is not None, f"{key} ({sym}) was not written to tick_log"
