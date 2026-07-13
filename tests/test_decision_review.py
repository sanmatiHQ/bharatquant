from __future__ import annotations

import time

from src.db.database import DB, DBConfig
from src.ops.decision_review import build_learning_review


def test_learning_review(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "lr.db")))
    db.add_cash(int(time.time()), 10_000.0, "seed")
    review = build_learning_review(db)
    assert "deployed_today_inr" in review
    assert "improvements" in review
    assert review["cash_inr"] == 10_000.0
