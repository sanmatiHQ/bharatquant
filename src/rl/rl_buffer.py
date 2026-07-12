"""
SQLite-backed replay buffer for RL observer mode.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, List, Tuple
import json
import time

from ..db.database import DB


@dataclass
class RLBuffer:
    db: DB

    def push(self, version: str, symbol: str, state: dict, action: str, reward: float, next_state: dict, done: bool) -> None:
        ts = int(time.time())
        payloads = (json.dumps(state).encode(), json.dumps(next_state).encode())
        with self.db.tx() as conn:
            conn.execute(
                """
                INSERT INTO rl_transitions(ts, version, symbol, state, action, reward, next_state, done)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, version, symbol, payloads[0], action, reward, payloads[1], int(done)),
            )

    def sample(self, n: int) -> list[tuple]:
        cur = self.db._conn.execute("SELECT id, ts, version, symbol, state, action, reward, next_state, done FROM rl_transitions ORDER BY RANDOM() LIMIT ?", (n,))
        return list(cur.fetchall())
