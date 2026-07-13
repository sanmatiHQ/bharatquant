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


def _load_enabled_strategies() -> Optional[List[str]]:
    cfg_path = os.getenv("CONFIG_YAML", "config.yaml")
    if not os.path.exists(cfg_path):
        return None
    with open(cfg_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("strategies", {}).get("enabled")


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
        asyncio.create_task(poll_global_macro(publish)),
        asyncio.create_task(poll_bulk_deals(publish, db=db)),
        asyncio.create_task(poll_session_status(publish)),
        asyncio.create_task(poll_akshare_fii(publish, db=db)),
        asyncio.create_task(poll_insider(publish, db=db)),
        asyncio.create_task(poll_preopen(publish, db=db)),
        asyncio.create_task(poll_delivery(publish, db=db)),
        asyncio.create_task(poll_corp_rss(publish, db=db)),
        asyncio.create_task(poll_option_iv(publish, db=db)),
        asyncio.create_task(poll_screener_loop(publish, symbols[:30], db=db)),
        asyncio.create_task(poll_token_health(publish)),
        asyncio.create_task(_poll_asm_gsm(db, logger)),
    ]
    logger.info("pollers_started", extra={"count": len(tasks)})
    return tasks


def _seed_paper_cash(db: DB, logger) -> None:
    if os.getenv("TRADING_MODE", "paper") != "paper":
        return
    row = db._conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()
    if float(row["c"]) != 0:
        return
    import time

    seed = float(os.getenv("PAPER_STARTING_CASH", "10000"))
    db.add_cash(int(time.time()), seed, "paper_seed")
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
    _seed_paper_cash(db, logger)

    enabled = _load_enabled_strategies()
    registry = StrategyRegistry(enabled=enabled)
    router = AgentRouter(db=db)
    context_updater = ContextUpdater(router.ctx, db=db)
    seed_calendar_year(db)
    sector_csv = os.getenv("SECTOR_MAP_CSV", "data/sector_map.csv")
    load_sector_map(db, sector_csv)
    from ..ops.agent_state import persist_context, touch_heartbeat

    persist_context(db, router.ctx)
    bandit = StrategyBandit(db)
    execution = ExecutionEngine(db, registry, router, bus_publish=bus.publish)
    pos_mon = PositionMonitor(db, bus.publish)
    bars = BarAggregator(bus.publish)
    recorder = TickRecorder(db)

    async def on_record(event: MarketEvent) -> None:
        await recorder.on_event(event)

    async def recorder_flush_loop() -> None:
        while True:
            await asyncio.sleep(30)
            recorder.flush()

    async def on_strategy_event(event: MarketEvent) -> None:
        await execution.on_event(event)

    async def on_tick(event: MarketEvent) -> None:
        await bars.on_tick(event)
        await pos_mon.on_tick(event)

    async def on_order_fill_event(event: MarketEvent) -> None:
        await on_order_fill(db, event)

    async def on_session_close(event: MarketEvent) -> None:
        await pos_mon.on_session_close(event)
        try:
            snapshot_portfolio_close(db)
            persist_daily_summary(db)
            backup_sqlite(os.getenv("SQLITE_PATH", "data/trading.db"))
            if os.getenv("RL_TRAIN_ON_CLOSE", "true").lower() in ("1", "true", "yes"):
                from ..rl.ppo_trainer import train_ppo
                from ..ops.gcs_store import sync_rl_model

                result = await asyncio.to_thread(
                    train_ppo,
                    db,
                    os.getenv("RL_MODEL_DIR", "models/rl"),
                    os.getenv("RL_ACTIVE_VERSION", "ppo_v1"),
                )
                logger.info("rl_train_on_close", extra=result)
                if result.get("status") == "ok":
                    await asyncio.to_thread(
                        sync_rl_model,
                        os.getenv("RL_MODEL_DIR", "models/rl"),
                        os.getenv("RL_ACTIVE_VERSION", "ppo_v1"),
                    )
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

    from ..portfolio.allocation import bootstrap_watchlist_allocation

    try:
        bootstrap_watchlist_allocation(db, watch_syms)
        logger.info("bootstrap_allocation_done", extra={"symbols": len(watch_syms)})
    except Exception:
        logger.exception("bootstrap_allocation_failed")

    async def on_pre_open(event: MarketEvent) -> None:
        """Screen full NSE universe before open — event-driven, not cron."""
        try:
            from ..portfolio.allocation import build_from_screen
            from ..screening.momentum_screener import MomentumScreener, ScreenerConfig

            scr = MomentumScreener(
                ScreenerConfig(
                    universe_csv=universe,
                    min_score=float(os.getenv("MIN_SCORE", "0.65")),
                    logs_dir=logs_dir,
                ),
                db,
            )
            df = await asyncio.to_thread(scr.run)
            logger.info("preopen_screen_done", extra={"hits": len(df), "universe": universe})
            if not df.empty:
                alloc = await asyncio.to_thread(build_from_screen, db, df)
                logger.info(
                    "preopen_allocation_done",
                    extra={"names": len(alloc), "symbols": alloc["symbol"].tolist() if not alloc.empty else []},
                )
                _restart_feed()
        except Exception:
            logger.exception("preopen_screen_failed")

    bus.subscribe(EventType.SESSION_PRE_OPEN, on_pre_open)

    kite_feed: Optional[KiteTickFeed] = None

    def _restart_feed() -> None:
        nonlocal kite_feed
        if kite_feed:
            kite_feed.stop()
        kite_feed = _start_kite_feed(bus, db, universe, logger)

    kite_feed = _start_kite_feed(bus, db, universe, logger)
    if kite_feed:
        watchdog.set_reconnect(_restart_feed)

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
    recorder_task = asyncio.create_task(recorder_flush_loop())
    watchdog_task = asyncio.create_task(watchdog.run_loop())

    async def heartbeat_loop() -> None:
        while True:
            try:
                touch_heartbeat(db)
                persist_context(db, router.ctx)
            except Exception:
                logger.exception("heartbeat_error")
            await asyncio.sleep(30)

    heartbeat_task = asyncio.create_task(heartbeat_loop())
    logger.info(
        "engine_started",
        extra={
            "mode": os.getenv("TRADING_MODE", "paper"),
            "strategies": len(registry._strategies),
            "universe": universe,
        },
    )

    try:
        await bus.run()
    finally:
        for t in poller_tasks:
            t.cancel()
        bandit_task.cancel()
        recorder_task.cancel()
        watchdog_task.cancel()
        heartbeat_task.cancel()
        recorder.flush()
        if kite_feed:
            kite_feed.stop()
        logger.info("engine_stopped")


if __name__ == "__main__":
    asyncio.run(main())
