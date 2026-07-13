"""Curated strategy rules from literature — feeds strategy_discovery mining."""
from __future__ import annotations

# Sources: QuantifiedStrategies.com, TradingView PROTOS, Kakushadze 151 Trading Strategies (SSRN 3247865)
LITERATURE_SOURCES = (
    "quantifiedstrategies",
    "tradingview_protos",
    "kakushadze_151",
)

# rule_id → metadata for dashboard / learning attribution
STRATEGY_LINEAGE: dict[str, dict] = {
    "connors_ibs": {
        "source": "quantifiedstrategies",
        "family": "mean_reversion",
        "refs": ["Connors RSI/IBS", "PROTOS #ibs"],
    },
    "crabel_nr7": {
        "source": "tradingview_protos",
        "family": "breakout",
        "refs": ["Crabel NR7", "151TS ch.3 channel"],
    },
    "zscore_reversion": {
        "source": "kakushadze_151",
        "family": "stat_arb",
        "refs": ["151TS mean-reversion clusters", "TV Reversal Pro z-score"],
    },
    "momentum_consensus": {
        "source": "tradingview_protos",
        "family": "momentum",
        "refs": ["Momentum Consensus Heatmap", "Quant Confluence Engine"],
    },
    "ema_cross_rsi": {
        "source": "tradingview_protos",
        "family": "trend",
        "refs": ["Smart Trend Dashboard", "EMA crossover + RSI"],
    },
    "liquidity_sweep": {
        "source": "tradingview_protos",
        "family": "smc",
        "refs": ["Liquidity Sweep & Golden Zone", "151TS channel breakout"],
    },
    "turnaround_tuesday": {
        "source": "quantifiedstrategies",
        "family": "calendar",
        "refs": ["Turnaround Tuesday", "151TS contrarian"],
    },
    "turtle_breakout": {
        "source": "kakushadze_151",
        "family": "breakout",
        "refs": ["Donchian channel", "Turtle traders"],
    },
    "short_term_reversal": {
        "source": "kakushadze_151",
        "family": "mean_reversion",
        "refs": ["5-day reversal", "Jegadeesh-Titman skip-month"],
    },
    "dual_momentum_pro": {
        "source": "quantifiedstrategies",
        "family": "momentum",
        "refs": ["Gary Antonacci dual momentum", "151TS 4.1.2"],
    },
    "india_power_hour": {
        "source": "quantifiedstrategies",
        "family": "session",
        "localized_from": "US_power_hour",
        "refs": ["QS session timing", "IST 14:30-15:30"],
    },
    "india_lunch_fade": {
        "source": "quantifiedstrategies",
        "family": "mean_reversion",
        "localized_from": "US_lunch_doldrums",
        "refs": ["QS intraday fade", "IST 12:00-13:30"],
    },
    "india_opening_drive": {
        "source": "quantifiedstrategies",
        "family": "session",
        "localized_from": "US_opening_drive",
        "refs": ["QS first-hour thrust", "IST 09:15-09:45"],
    },
    "nifty_buy_the_dip": {
        "source": "quantifiedstrategies",
        "family": "mean_reversion",
        "localized_from": "SPY_buy_the_dip",
        "refs": ["QS buy the dip", "NIFTYBEES proxy"],
    },
    "india_dual_rotation": {
        "source": "quantifiedstrategies",
        "family": "momentum",
        "localized_from": "SPY_TLT_rotation",
        "refs": ["Antonacci dual momentum", "NIFTYBEES vs GOLDBEES"],
    },
    "ath_breakout_in": {
        "source": "quantifiedstrategies",
        "family": "breakout",
        "localized_from": "ATH_breakout",
        "refs": ["QS all-time-high breakout", "Donchian high_20"],
    },
    "lower_highs_fade": {
        "source": "quantifiedstrategies",
        "family": "distribution",
        "localized_from": "lower_highs_lower_lows",
        "refs": ["QS LH distribution", "151TS contrarian"],
    },
    "us_overnight_follow": {
        "source": "quantifiedstrategies",
        "family": "overnight",
        "localized_from": "US_overnight_drift",
        "refs": ["GIFT gap follow-through", "US close → NSE open"],
    },
    "expiry_week_caution": {
        "source": "quantifiedstrategies",
        "family": "calendar",
        "localized_from": "US_monthly_OPEX",
        "refs": ["India monthly expiry Thu", "defensive fade"],
    },
    "monday_effect_in": {
        "source": "quantifiedstrategies",
        "family": "calendar",
        "localized_from": "US_Monday_effect",
        "refs": ["Monday reversal", "GIFT weekend gap"],
    },
}

# Discovery mining rules — field must exist in bar_log-derived features or recomputed in miner
DISCOVERY_RULES: tuple[dict, ...] = (
    {"rule_id": "mom_r3m_pos", "field": "r3m", "op": "gt", "threshold": 0.006, "source": "kakushadze_151"},
    {"rule_id": "mom_rsi_os", "field": "rsi", "op": "lt", "threshold": 35, "source": "quantifiedstrategies"},
    {"rule_id": "vol_spike", "field": "vol_ratio", "op": "gt", "threshold": 2.0, "source": "tradingview_protos"},
    {"rule_id": "ibs_oversold", "field": "ibs", "op": "lt", "threshold": 0.2, "source": "quantifiedstrategies"},
    {"rule_id": "ibs_overbought", "field": "ibs", "op": "gt", "threshold": 0.8, "source": "quantifiedstrategies"},
    {"rule_id": "zscore_stretch_dn", "field": "z_score", "op": "lt", "threshold": -2.0, "source": "kakushadze_151"},
    {"rule_id": "zscore_stretch_up", "field": "z_score", "op": "gt", "threshold": 2.0, "source": "kakushadze_151"},
    {"rule_id": "nr7_breakout", "field": "nr7", "op": "gt", "threshold": 0, "source": "tradingview_protos"},
    {"rule_id": "ema_trend_up", "field": "ema_cross_up", "op": "gt", "threshold": 0, "source": "tradingview_protos"},
    {"rule_id": "donchian_high_brk", "field": "donchian_brk", "op": "gt", "threshold": 0, "source": "kakushadze_151"},
    {"rule_id": "near_high_20_brk", "field": "near_high_20", "op": "gt", "threshold": 0, "source": "quantifiedstrategies"},
    {"rule_id": "lower_high_streak", "field": "lower_high_streak", "op": "gt", "threshold": 1, "source": "quantifiedstrategies"},
)
