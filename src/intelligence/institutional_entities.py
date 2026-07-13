"""Classify bulk/insider client names — MF, FII, bank, promoter (no LLM)."""
from __future__ import annotations

import re

_MF_KW = (
    "mutual fund",
    " mf ",
    "mf ",
    " mf",
    "amc",
    "asset management",
    "fund house",
    "pms",
    "portfolio management",
    "sbi magnum",
    "nippon",
    "hdfc mutual",
    "icici prudential",
    "kotak mutual",
    "axis mutual",
    "uti ",
    "franklin",
    "dsp ",
    "mirae",
    "parag parikh",
    "quant mutual",
    "bandhan",
    "tata mutual",
)
_FII_KW = (
    "fii",
    "foreign",
    "offshore",
    "mauritius",
    "singapore",
    "cayman",
    "luxembourg",
    "goldman",
    "morgan stanley",
    "jpmorgan",
    "citigroup",
    "ubs ",
    "nomura",
    "credit suisse",
    "deutsche",
    "barclays",
    "blackrock",
    "vanguard",
)
_BANK_KW = (
    "bank",
    "hdfc bank",
    "icici bank",
    "axis bank",
    "kotak bank",
    "sbi ",
    "state bank",
    "yes bank",
    "idfc",
    "indusind",
    "rbl bank",
    "punjab national",
    "canara bank",
    "union bank",
)
_PROMOTER_KW = ("promoter", "promoter group", "director", "kmp", "managing director", "ceo")


def classify_entity(name: str) -> str:
    """Return mf | fii | bank | promoter | other."""
    raw = (name or "").strip()
    if not raw:
        return "other"
    t = f" {raw.lower()} "
    if any(k in t for k in _PROMOTER_KW):
        return "promoter"
    if any(k in t for k in _MF_KW):
        return "mf"
    if any(k in t for k in _FII_KW):
        return "fii"
    if any(k in t for k in _BANK_KW):
        return "bank"
    if re.search(r"\bfund\b", t):
        return "mf"
    return "other"


def entity_confidence_boost(entity_class: str, side: str) -> float:
    """Static prior before learned weights — institutional names matter more."""
    if entity_class in ("mf", "fii") and side == "buy":
        return 0.06
    if entity_class in ("mf", "fii") and side == "sell":
        return 0.05
    if entity_class == "bank" and side == "buy":
        return 0.03
    if entity_class == "promoter" and side == "buy":
        return 0.04
    return 0.0
