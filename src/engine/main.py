"""
Always-on event-driven trading engine entrypoint.
No trading cron — reacts to MarketEvent stream only.

Run on GCE: python3.11 -m src.engine.main
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import List, Optional

import yaml
from dotenv import load_dotenv

from ..agent.bandit import StrategyBandit
from ..agent.context_updater import ContextUpdater
from ..agent.router import AgentRouter
from ..db.database import DB, DBConfig
from .execution_engine import ExecutionEngine
from ..events import EventBus, EventType, MarketEvent
from ..exec.position_monitor import PositionMonitor
from ..feeds.bar_aggregator import BarAggregator
from ..feeds.kite_ticker import KiteTickFeed, load_access_token
from ..feeds.session_watcher import poll_session_status
from ..data.tick_recorder import TickRecorder
from ..ingest.fii_dii import poll_fii_dii
from ..ingest.gift_nifty import poll_gift_proxy
from ..ingest.global_macro import poll_global_macro
from ..ingest.nse_bulk import poll_bulk_deals
from ..ingest.akshare_fii import poll_akshare_fii
from ..ingest.nse_insider import poll_insider
from ..ingest.nse_preopen import poll_preopen
from ..ingest.nse_delivery import poll_delivery
from ..ingest.nse_corp_rss import poll_corp_rss
from ..ingest.screener_fundamentals import poll_screener_loop
from ..ingest.kite_options import poll_option_iv
from ..ops.backup import backup_sqlite
from ..ops.daily_pnl import snapshot_portfolio_close
from ..ops.daily_tax_summary import persist_daily_summary
from ..ops.auth_recovery import handle_auth_event, poll_token_health
from ..exec.order_fill_handler import on_order_fill
from ..data.sector_mapper import load_sector_map
from ..risk.event_calendar import seed_calendar_year
from ..data.asm_gsm_filter import fetch_asm_gsm, sync_asm_gsm_db
from ..feeds.feed_watchdog import FeedWatchdog
from ..data.instruments import InstrumentStore
from ..data.watchlist import load_watchlist_symbols
from ..strategies.registry import StrategyRegistry
from ..utils.logging_setup import get_logger

load_dotenv()


def _load_config() -> dict:
    cfg_path = os.getenv("CONFIG_YAML", "config.yaml")
    if not os.path.exists(cfg_path):
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_enabled_strategies() -> Optional[List[str]]:
    return _load_config().get("strategies", {}).get("enabled")


async def _poll_asm_gsm(db: DB, logger) -> None:
    import asyncio

    while True:
        try:
            rows = await fetch_asm_gsm()
            n = sync_asm_gsm_db(db, rows)
            logger.info("asm_gsm_synced", extra={"count": n})
        except Exception:
            logger.exception("asm_gsm_sync_error")
        await asyncio.sleep(3600.0)


async def _start_pollers(bus: EventBus, logger, db: DB, symbols: list[str]) -> List[asyncio.Task]:
    publish = bus.publish
    tasks = [
        asyncio.create_task(poll_fii_dii(publish, db=db)),
        asyncio.create_task(poll_gift_proxy(publish, db=db)),
        asyncio.create_task(poll_global_macro(publish, db=db)),
        asyncio.create_task(poll_bulk_deals(publish, db=db)),
        asyncio.create_task(poll_session_status(publish)),
        asyncio.create_task(poll_akshare_fii(publish, db=db)),
        asyncio.create_task(poll_insider(publish, db=db)),
        asyncio.create_task(poll_preopen(publish, db=db)),
        asyncio.create_task(poll_delivery(publish, db=db)),
        asyncio.create_task(poll_corp_rss(publish, db=db)),
        asyncio.create_task(poll_option_iv(publish, db=db)),
    ]
    from ..ingest.nse_shareholding import poll_shareholding

    tasks.extend(
        [
            asyncio.create_task(poll_shareholding(publish, db=db)),
        ]
    )
    tasks.extend(
        [
            asyncio.create_task(poll_screener_loop(publish, symbols[:30], db=db)),
            asyncio.create_task(poll_token_health(publish)),
            asyncio.create_task(_poll_asm_gsm(db, logger)),
        ]
    )
    from ..ingest.kite_holdings import poll_kite_holdings
    from ..intelligence.strategy_discovery import discovery_loop

    tasks.append(asyncio.create_task(poll_kite_holdings(db)))
    tasks.append(asyncio.create_task(discovery_loop(db)))

    from ..ingest.llm_macro import poll_llm_macro
    from ..ingest.futures_oi import poll_futures_oi
    from ..ops.reconciliation import run_reconciliation_loop
    from ..ops.margin_monitor import run_margin_monitor_loop
    from ..ops.mis_squareoff import run_mis_squareoff_loop

    tasks.append(asyncio.create_task(poll_llm_macro(publish, db)))
    tasks.append(asyncio.create_task(poll_futures_oi(publish, db)))
    from ..ingest.nse_corporate_calendar import poll_corporate_calendar
    from ..ingest.nse_participant_oi import poll_participant_oi
    from ..ingest.bse_announcements import poll_bse_announcements

    tasks.extend(
        [
            asyncio.create_task(poll_corporate_calendar(publish, db=db)),
            asyncio.create_task(poll_participant_oi(publish, db=db)),
            asyncio.create_task(poll_bse_announcements(publish, db=db)),
        ]
    )
    tasks.append(asyncio.create_task(run_reconciliation_loop(db, publish=publish)))
    tasks.append(asyncio.create_task(run_margin_monitor_loop(db)))
    tasks.append(asyncio.create_task(run_mis_squareoff_loop(db, publish)))
    logger.info("pollers_started", extra={"count": len(tasks)})
    return tasks


def _seed_paper_cash(db: DB, logger) -> None:
    """Seed paper cash once only — never auto top-up (user sets budget via daily cap)."""
    if os.getenv("TRADING_MODE", "paper") != "paper":
        return
    import time

    row = db._conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()
    balance = float(row["c"])
    if balance != 0:
        logger.info("paper_cash_unchanged", extra={"balance": balance})
        return
    seed = float(os.getenv("PAPER_STARTING_CASH", "5000"))
    db.add_cash(int(time.time()), seed, "paper_seed_once")
    logger.info("paper_cash_seeded", extra={"amount": seed})


def _start_kite_feed(
    bus: EventBus,
    db: DB,
    universe_csv: str,
    logger,
) -> Optional[KiteTickFeed]:
    from ..ops.healthchecks import check_token

    if not check_token(live=True):
        logger.error("kite_token_invalid", extra={"hint": "re-login via /login"})
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(
            bus.publish_nowait,
            MarketEvent(type=EventType.TOKEN_EXPIRED, payload={"reason": "startup_check"}),
        )
        return None
    try:
        api_key, token = load_access_token()
    except Exception as e:
        logger.warning("kite_feed_skipped", extra={"reason": str(e)})
        return None

    store = InstrumentStore(db)
    store.ensure_cache(universe_csv=universe_csv)
    watch = load_watchlist_symbols(db)
    if not watch:
        # First boot before SESSION_PRE_OPEN screen — liquid NSE names for WS subscription
        watch = [
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL",
            "ITC", "KOTAKBANK", "LT", "AXISBANK", "MARUTI", "BAJFINANCE", "HINDUNILVR",
            "ASIANPAINT", "TITAN", "SUNPHARMA", "WIPRO", "ULTRACEMCO", "NESTLEIND",
            "ONGC", "POWERGRID", "NTPC", "COALINDIA", "TATASTEEL", "VEDL", "IOC",
        ]
        cap = int(os.getenv("WS_WATCHLIST_SIZE", "200"))
        watch = watch[:cap]
        logger.info("kite_feed_bootstrap_watchlist", extra={"count": len(watch)})

    token_map: dict[int, str] = {}
    for sym in watch:
        try:
            token_map[store.token_for(sym)] = sym.replace("NSE:", "")
        except KeyError:
            continue

    if not token_map:
        logger.warning("kite_feed_no_tokens")
        return None

    loop = asyncio.get_running_loop()

    def on_tick(ev: MarketEvent) -> None:
        loop.call_soon_threadsafe(bus.publish_nowait, ev)

    feed = KiteTickFeed(api_key, token, on_tick)
    feed.start(token_map)
    logger.info(
        "kite_feed_started",
        extra={"watchlist": len(token_map), "universe_csv": universe_csv},
    )
    return feed


async def main() -> None:
    logs_dir = os.getenv("LOGS_DIR", "logs")
    logger = get_logger("engine", logs_dir=logs_dir)
    bus = EventBus()
    db = DB(DBConfig(sqlite_path=os.getenv("SQLITE_PATH", "data/trading.db")))
    from ..ops.agent_state import touch_heartbeat, persist_engine_phase

    touch_heartbeat(db)
    persist_engine_phase(db, "BOOT")
    _seed_paper_cash(db, logger)
    from ..ops.trading_phase import assert_live_mode_allowed, evaluate_live_gate

    live_ok, live_msg = assert_live_mode_allowed(db)
    if not live_ok:
        logger.error("live_gate_blocked", extra={"reason": live_msg})
        os.environ["TRADING_MODE"] = "paper"
    phase_info = evaluate_live_gate(db)
    logger.info(
        "trading_phase",
        extra={"phase": phase_info["phase"], "live_gate": phase_info["live_gate_eligible"]},
    )

    enabled = _load_enabled_strategies()
    cfg = _load_config()
    registry = StrategyRegistry(enabled=enabled, db=db, config=cfg)
    router = AgentRouter(db=db)
    context_updater = ContextUpdater(router.ctx, db=db)
    from ..market.market_awareness import refresh_market_awareness

    refresh_market_awareness(router.ctx, db)
    seed_calendar_year(db)
    sector_csv = os.getenv("SECTOR_MAP_CSV", "data/sector_map.csv")
    load_sector_map(db, sector_csv)
    from ..ops.agent_state import persist_context, touch_heartbeat, persist_engine_phase

    persist_context(db, router.ctx)
    bandit = StrategyBandit(db)
    execution = ExecutionEngine(db, registry, router, bus_publish=bus.publish)
    pos_mon = PositionMonitor(db, bus.publish)
    bars = BarAggregator(bus.publish)
    recorder = TickRecorder(db, flush_every=int(os.getenv("TICK_FLUSH_EVERY", "50")))

    async def on_record(event: MarketEvent) -> None:
        asyncio.create_task(recorder.on_event(event))

    async def recorder_flush_loop() -> None:
        while True:
            await asyncio.sleep(30)
            recorder.flush()

    async def on_strategy_event(event: MarketEvent) -> None:
        from ..engine.fast_snapshot import is_fast_path_enabled

        if is_fast_path_enabled() and event.type == EventType.TICK:
            exit_sigs = await registry.dispatch_exits_only(event, router.ctx)
            if exit_sigs:
                chosen = router.fuse(
                    exit_sigs,
                    event_price=float(event.price or 0),
                    event_symbol=event.symbol or "",
                )
                if chosen:
                    await execution.on_event(
                        MarketEvent(
                            type=EventType.FAST_SNAPSHOT,
                            symbol=chosen.symbol,
                            price=float(event.price or 0),
                            payload={
                                "strategy_id": chosen.strategy_id,
                                "action": chosen.action,
                                "rail": chosen.rail,
                                "confidence": chosen.confidence,
                                "reason": chosen.reason,
                            },
                        )
                    )
            return
        await execution.on_event(event)

    async def on_tick(event: MarketEvent) -> None:
        await bars.on_tick(event)
        await pos_mon.on_tick(event)

    async def on_order_fill_event(event: MarketEvent) -> None:
        await on_order_fill(db, event)

    async def on_session_close(event: MarketEvent) -> None:
        await pos_mon.on_session_close(event)
        try:
            from ..ops.budget_gate import rollover_at_session_close
            from ..intelligence.eod_market_scan import run_eod_scan_async

            rollover_at_session_close(db)
            eod = await run_eod_scan_async(db, universe)
            logger.info("eod_scan_complete", extra=eod)
            snapshot_portfolio_close(db)
            persist_daily_summary(db)
            backup_sqlite(os.getenv("SQLITE_PATH", "data/trading.db"))
            defer_rl = os.getenv("POSTMARKET_RL_DEFER", "true").lower() in ("1", "true", "yes")
            if not defer_rl and os.getenv("RL_TRAIN_ON_CLOSE", "true").lower() in ("1", "true", "yes"):
                from ..ops.gcs_store import sync_rl_model
                from ..rl.training_guardrails import guarded_train_and_promote

                result = await asyncio.to_thread(
                    guarded_train_and_promote,
                    db,
                    os.getenv("RL_MODEL_DIR", "models/rl"),
                    os.getenv("RL_ACTIVE_VERSION", "ppo_v1"),
                )
                logger.info("rl_train_on_close", extra=result)
                if result.get("promoted") and result.get("train", {}).get("status") == "ok":
                    await asyncio.to_thread(
                        sync_rl_model,
                        os.getenv("RL_MODEL_DIR", "models/rl"),
                        os.getenv("RL_ACTIVE_VERSION", "ppo_v1"),
                    )
            elif defer_rl:
                logger.info("rl_train_deferred_to_postmarket")
        except Exception:
            logger.exception("session_close_ops_failed")

    context_updater.subscribe(bus)

    async def on_auth_event(event: MarketEvent) -> None:
        await handle_auth_event(event, restart_feed=lambda: _start_kite_feed(bus, db, universe, logger))

    bus.subscribe(EventType.TOKEN_EXPIRED, on_auth_event)
    bus.subscribe(EventType.WS_AUTH_FAIL, on_auth_event)

    watchdog = FeedWatchdog(bus.publish)
    bus.subscribe(EventType.TICK, watchdog.on_tick)

    bus.subscribe_many(list(EventType), on_strategy_event)
    bus.subscribe(EventType.ORDER_FILL, on_order_fill_event)
    bus.subscribe(EventType.TICK, on_tick)
    bus.subscribe(EventType.TICK, on_record)
    bus.subscribe(EventType.BAR_CLOSE_5M, on_record)
    bus.subscribe(EventType.BAR_CLOSE_15M, on_record)
    bus.subscribe(EventType.BAR_CLOSE_1D, on_record)
    bus.subscribe(EventType.SESSION_CLOSE, on_session_close)

    universe = os.getenv("UNIVERSE", "data/universe_full_nse.csv")
    instrument_store = InstrumentStore(db)
    instrument_store.ensure_cache(universe_csv=universe)
    watch_syms = load_watchlist_symbols(db) or ["INFY", "TCS", "RELIANCE"]

    poller_tasks = await _start_pollers(bus, logger, db, watch_syms)

    from ..ops.reconciliation import startup_position_audit

    await startup_position_audit(db)

    from ..ingest.llm_macro import compute_llm_bias

    try:
        ctx_raw = db._conn.execute("SELECT v FROM settings WHERE k='agent_context'").fetchone()
        import json

        ctx = json.loads(ctx_raw["v"]) if ctx_raw else {}
        router.ctx.llm_bias = await compute_llm_bias(db, ctx)
    except Exception:
        logger.exception("startup_llm_bias_failed")
        router.ctx.llm_bias = 0.0

    from ..portfolio.allocation import bootstrap_watchlist_allocation

    try:
        bootstrap_watchlist_allocation(db, watch_syms)
        logger.info("bootstrap_allocation_done", extra={"symbols": len(watch_syms)})
    except Exception:
        logger.exception("bootstrap_allocation_failed")

    async def on_pre_open(event: MarketEvent) -> None:
        """Screen full NSE universe before open — parallel OHLC across ~2300 names."""
        try:
            from ..ops.budget_gate import credit_daily_stipend_on_open
            from ..screening.screen_orchestrator import run_full_screen

            stipend = credit_daily_stipend_on_open(db)
            logger.info("daily_stipend", extra=stipend)
            await run_full_screen(db, universe, logs_dir, reason="session_pre_open", on_complete=_restart_feed)
        except Exception:
            logger.exception("preopen_screen_failed")

    async def on_session_open(event: MarketEvent) -> None:
        try:
            from ..ops.budget_gate import credit_daily_stipend_on_open

            stipend = credit_daily_stipend_on_open(db)
            logger.info("session_open_stipend", extra=stipend)
        except Exception:
            logger.exception("session_open_stipend_failed")

    bus.subscribe(EventType.SESSION_PRE_OPEN, on_pre_open)
    bus.subscribe(EventType.SESSION_OPEN, on_session_open)

    kite_feed: Optional[KiteTickFeed] = None

    def _restart_feed() -> None:
        nonlocal kite_feed
        if kite_feed:
            kite_feed.stop()
        kite_feed = _start_kite_feed(bus, db, universe, logger)

    kite_feed = _start_kite_feed(bus, db, universe, logger)
    if kite_feed:
        watchdog.set_reconnect(_restart_feed)

    from ..ops.budget_gate import credit_daily_stipend_on_open
    from ..screening.screen_orchestrator import ensure_fresh_screen
    from ..feeds.batch_ltp_watcher import poll_batch_ltp_loop

    try:
        logger.info("startup_stipend", extra=credit_daily_stipend_on_open(db))
    except Exception:
        logger.exception("startup_stipend_failed")

    async def _startup_screen() -> None:
        try:
            await ensure_fresh_screen(db, universe, logs_dir, on_complete=_restart_feed)
        except Exception:
            logger.exception("startup_screen_failed")

    screen_task = asyncio.create_task(_startup_screen())
    batch_ltp_task = asyncio.create_task(poll_batch_ltp_loop(db, universe))

    loop = asyncio.get_running_loop()

    def _stop() -> None:
        bus.stop()
        if kite_feed:
            kite_feed.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    async def refresh_bandit() -> None:
        while True:
            try:
                for sid, w in bandit.update_weights().items():
                    router.set_weight(sid, w)
            except Exception:
                logger.exception("bandit_refresh_error")
            await asyncio.sleep(3600)

    bandit_task = asyncio.create_task(refresh_bandit())

    async def strategy_learn_loop() -> None:
        from ..intelligence.strategy_learning import refresh_all_learning

        while True:
            try:
                meta = refresh_all_learning(db, ctx)
                for sid, w in bandit.update_weights().items():
                    router.set_weight(sid, w)
                logger.info("strategy_learn_cycle", extra=meta)
            except Exception:
                logger.exception("strategy_learn_error")
            await asyncio.sleep(1800)

    learn_task = asyncio.create_task(strategy_learn_loop())
    recorder_task = asyncio.create_task(recorder_flush_loop())
    watchdog_task = asyncio.create_task(watchdog.run_loop())

    async def heartbeat_loop() -> None:
        from ..ops.budget_gate import expire_pending_if_stale
        from ..ops.trading_phase import evaluate_live_gate

        while True:
            try:
                touch_heartbeat(db)
                persist_engine_phase(db)
                persist_context(db, router.ctx)
                pos_mon.refresh_vix()
                expire_pending_if_stale(db)
                evaluate_live_gate(db)
            except Exception:
                logger.exception("heartbeat_error")
            await asyncio.sleep(30)

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    from ..ops.market_routines import market_routines_loop
    from ..market.market_awareness import market_clock_loop

    routines_task = asyncio.create_task(
        market_routines_loop(db, router.ctx, rl_agent=router._rl_agent, publish=bus.publish)
    )
    clock_task = asyncio.create_task(market_clock_loop(router.ctx, db))
    logger.info(
        "engine_started",
        extra={
            "mode": os.getenv("TRADING_MODE", "paper"),
            "strategies": len(registry._strategies),
            "universe": universe,
        },
    )

    from ..engine.fast_snapshot import is_fast_path_enabled, run_fast_decision_loop

    fast_task = None
    if is_fast_path_enabled():
        fast_task = asyncio.create_task(run_fast_decision_loop(db, router.ctx, bus.publish))

    try:
        await bus.run()
    finally:
        for t in poller_tasks:
            t.cancel()
        bandit_task.cancel()
        learn_task.cancel()
        recorder_task.cancel()
        watchdog_task.cancel()
        heartbeat_task.cancel()
        routines_task.cancel()
        clock_task.cancel()
        screen_task.cancel()
        batch_ltp_task.cancel()
        if fast_task:
            fast_task.cancel()
        recorder.flush()
        if kite_feed:
            kite_feed.stop()
        logger.info("engine_stopped")


if __name__ == "__main__":
    asyncio.run(main())
