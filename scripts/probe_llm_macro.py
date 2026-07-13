#!/usr/bin/env python3.11
"""One-shot LLM macro activation smoke test on VM."""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, "/opt/bharatquant/zerodha-momo-rl")

from dotenv import load_dotenv

load_dotenv("/etc/bharatquant/env")

from src.db.database import DB, DBConfig
from src.ingest.llm_macro import compute_llm_bias


async def main() -> None:
    db = DB(DBConfig(sqlite_path=os.environ["SQLITE_PATH"]))
    ctx = {
        "fii_net_cr": 200,
        "dii_net_cr": 100,
        "gift_pct": 0.1,
        "india_vix": 14,
        "headlines": ["Markets steady ahead of RBI policy"],
    }
    bias = await compute_llm_bias(db, ctx)
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", ("llm_macro_bias",)).fetchone()
    print("LLM_ENABLED", os.getenv("LLM_ENABLED"))
    print("VERTEX_GEMINI", os.getenv("VERTEX_GEMINI_ENABLED"), os.getenv("VERTEX_GEMINI_MODEL"))
    print("GEMINI_KEY_SET", bool(os.getenv("GEMINI_API_KEY")))
    print("llm_bias", bias)
    detail = db._conn.execute("SELECT v FROM settings WHERE k=?", ("llm_macro_detail",)).fetchone()
    print("source", (json.loads(detail["v"]).get("source") if detail else "none"))


if __name__ == "__main__":
    asyncio.run(main())
