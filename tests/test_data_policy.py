"""Data integrity policy tests."""
from __future__ import annotations

import pytest

from src.data.data_policy import DataIntegrityError, require_positive_price


def test_require_positive_price_ok():
    assert require_positive_price(100.5, "INFY") == 100.5


def test_require_positive_price_rejects_zero():
    with pytest.raises(DataIntegrityError):
        require_positive_price(0, "INFY")
