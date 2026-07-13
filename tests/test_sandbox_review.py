"""Sandbox review API tests."""
from __future__ import annotations

from src.db.database import DB, DBConfig
from src.intelligence.sandbox_review import build_sandbox_review


def test_sandbox_review_shape(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "sb.db")))
    review = build_sandbox_review(db)
    assert "promote_recommendation" in review
    assert "history_days" in review
    assert review["rl_version"]
