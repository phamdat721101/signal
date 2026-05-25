"""Scheduler — runs card generation + signal resolution + position monitoring."""
import json
import logging
import time
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


_TIER_THRESHOLDS = [
    (0, 10, 0, 0),      # BRONZE_APE: 10 wins
    (1, 0, 5000, 50),    # SILVER_APE: 50% rate + 50 trades
    (2, 100, 0, 0),      # GOLD_APE: 100 wins
    (3, 0, 0, 0),        # DIAMOND_HANDS: 10 streak (special)
    (4, 0, 8000, 100),   # SIGNAL_SAGE: 80% rate + 100 trades
]

def _check_achievements(chain, user_address: str):
    try:
        stats = chain.get_user_stats(user_address)
        wins = stats["wins"]
        total = stats["totalTrades"]
        rate = int(wins / total * 10000) if total > 0 else 0
        streak = stats["bestStreak"]
        for tier, min_wins, min_rate, min_trades in _TIER_THRESHOLDS:
            qualifies = False
            if tier == 0: qualifies = wins >= 10
            elif tier == 1: qualifies = rate >= 5000 and total >= 50
            elif tier == 2: qualifies = wins >= 100
            elif tier == 3: qualifies = streak >= 10
            elif tier == 4: qualifies = rate >= 8000 and total >= 100
            if qualifies and not chain.has_tier(user_address, tier):
                chain.mint_achievement(user_address, tier, wins, rate, streak)
                logger.info(f"Minted tier {tier} for {user_address}")
    except Exception as e:
        logger.warning(f"Achievement check failed for {user_address}: {e}")


def monitor_positions():
    """Update PnL for all open trades. Auto-resolve trades > 24h old."""
    from app.db import get_unresolved_trades, update_trade_pnl
    from app.signal_engine import fetch_coingecko_fallback, COINGECKO_IDS

    trades = get_unresolved_trades()
    if not trades:
        return

    # Batch fetch prices for unique symbols
    symbols = {t["token_symbol"] for t in trades}
    cg_ids = {sym: COINGECKO_IDS.get(f"{sym}/USD", "") for sym in symbols}
    ids_str = ",".join(v for v in cg_ids.values() if v)

    prices = {}
    if ids_str:
        try:
            import httpx
            resp = httpx.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ids_str, "vs_currencies": "usd"}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                id_to_sym = {v: k for k, v in cg_ids.items() if v}
                for cg_id, vals in data.items():
                    if cg_id in id_to_sym and "usd" in vals:
                        prices[id_to_sym[cg_id]] = vals["usd"]
        except Exception as e:
            logger.warning(f"Position monitor price fetch failed: {e}")

    # Retry once after delay if no prices
    if not prices and ids_str:
        time.sleep(2)
        try:
            import httpx
            resp = httpx.get("https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ids_str, "vs_currencies": "usd"}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                id_to_sym = {v: k for k, v in cg_ids.items() if v}
                for cg_id, vals in data.items():
                    if cg_id in id_to_sym and "usd" in vals:
                        prices[id_to_sym[cg_id]] = vals["usd"]
        except Exception:
            pass

    if not prices:
        return

    now = time.time()
    updated = 0
    for t in trades:
        sym = t["token_symbol"]
        entry = t["entry_price"]
        if entry <= 0:
            continue

        # SoDex trades: use SoDex ticker + TP/SL close orders
        if t.get("execution_type") == "sodex":
            try:
                from app.sodex_client import get_ticker, place_close_order, map_symbol
                sodex_sym = map_symbol(sym)
                ticker = get_ticker(sodex_sym)
                current_price = float(ticker.get("last_price", 0))
                if current_price <= 0:
                    continue
                pnl_pct = (current_price - entry) / entry * 100
                pnl_usd = t["amount_usd"] * pnl_pct / 100
                # TP/SL check (±1.5%)
                tp_price = entry * 1.015
                sl_price = entry * 0.985
                created = t["created_at"]
                age_hours = (now - created.timestamp()) / 3600 if hasattr(created, "timestamp") else 0
                should_close = current_price >= tp_price or current_price <= sl_price or age_hours > 24
                if should_close:
                    place_close_order(sodex_sym, "sell", t["token_amount"])
                update_trade_pnl(t["id"], current_price, round(pnl_usd, 4), round(pnl_pct, 2), should_close)
                updated += 1
            except Exception as e:
                logger.warning(f"SoDex position monitor failed for trade {t['id']}: {e}")
            continue

        current_price = prices.get(sym)
        if current_price is None:
            continue
        entry = t["entry_price"]
        if entry <= 0:
            continue
        pnl_pct = (current_price - entry) / entry * 100
        pnl_usd = t["amount_usd"] * pnl_pct / 100
        # Auto-resolve after 24h
        created = t["created_at"]
        age_hours = 0
        if hasattr(created, "timestamp"):
            age_hours = (now - created.timestamp()) / 3600
        resolve = age_hours > 24
        update_trade_pnl(t["id"], current_price, round(pnl_usd, 4), round(pnl_pct, 2), resolve)
        updated += 1
        # Task 3: Wire to RewardEngine on resolution
        if resolve:
            try:
                from app.config import get_settings
                from app.main import normalize_address
                settings = get_settings()
                if settings.contract_address and settings.reward_engine_address:
                    from app.chain import ChainClient
                    chain = ChainClient()
                    user_addr = normalize_address(t["user_address"])
                    was_profit = pnl_usd > 0
                    chain.on_trade_resolved(user_addr, was_profit, int(t["amount_usd"] * 1e18))
                    _check_achievements(chain, user_addr)
                # ConvictionEngine: resolve card convictions
                if settings.conviction_engine_address:
                    import hashlib
                    from app.db import get_card_by_id
                    card = get_card_by_id(t["card_id"])
                    if card:
                        card_json = json.dumps({"id": t["card_id"], "symbol": card["token_symbol"],
                                                "hook": card.get("hook", ""), "verdict": card.get("verdict", "")}, sort_keys=True)
                        card_hash = bytes.fromhex(hashlib.sha256(card_json.encode()).hexdigest())
                        if not hasattr(self, '_chain_inst'):
                            from app.chain import ChainClient
                            chain = ChainClient()
                        chain.resolve_card_conviction(card_hash, pnl_usd > 0)
                        logger.info(f"Conviction resolved for card {t['card_id']}")
            except Exception as e:
                logger.warning(f"Resolution hooks failed for trade {t['id']}: {e}")

    if updated:
        logger.info(f"Position monitor: updated {updated}/{len(trades)} trades")


def expire_old_cards():
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE cards SET status='expired' WHERE expires_at < NOW() AND status = 'active'")
        if cur.rowcount:
            logger.info(f"Expired {cur.rowcount} cards")


def resolve_expired_escrows():
    """Auto-resolve escrows older than 24h based on price outcome."""
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        return
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT e.id, e.signal_id, e.escrow_contract, e.amount_usdc,
                       c.token_symbol, c.price as entry_price, c.verdict
                FROM signal_escrows e
                JOIN cards c ON c.id = e.signal_id
                WHERE e.status = 'funded' AND e.created_at < NOW() - INTERVAL '24 hours'
                LIMIT 10
            """)
            rows = cur.fetchall()
        if not rows:
            return
        from app.price_feed import get_prices
        import asyncio
        from app.trustless_escrow import resolve_signal_escrow
        for row in rows:
            try:
                prices = get_prices([row["token_symbol"]])
                current_price = prices.get(row["token_symbol"], {}).get("price", 0)
                if not current_price or not row["entry_price"]:
                    continue
                is_bull = row["verdict"] == "APE"
                pnl_pct = (current_price - row["entry_price"]) / row["entry_price"] * 100
                profitable = (pnl_pct > 0) if is_bull else (pnl_pct < 0)
                evidence = f"{row['token_symbol']}: entry={row['entry_price']:.4f} current={current_price:.4f} pnl={pnl_pct:.2f}%"
                asyncio.get_event_loop().run_until_complete(
                    resolve_signal_escrow(row["escrow_contract"], profitable, evidence)
                )
                with conn.cursor() as cur2:
                    cur2.execute(
                        "UPDATE signal_escrows SET status=%s, profitable=%s, evidence=%s, resolved_at=NOW() WHERE id=%s",
                        ("resolved" if profitable else "refunded", profitable, evidence, row["id"]))
                logger.info(f"Escrow {row['escrow_contract']} resolved: profitable={profitable}")
            except Exception as e:
                logger.warning(f"Escrow resolution failed for {row['id']}: {e}")
    except Exception as e:
        logger.warning(f"resolve_expired_escrows error: {e}")


def resolve_report_escrows():
    """Resolve premium report escrows: retry failed generations, expire stale, release delivered."""
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        return
    try:
        from psycopg2.extras import RealDictCursor
        # 1. Retry 'funded' reports that failed generation (max 3 retries)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, report_type, retry_count FROM report_escrows
                WHERE status='funded' AND retry_count < 3 AND funded_at < NOW() - INTERVAL '1 minute'
                LIMIT 5
            """)
            to_retry = cur.fetchall()
        for row in to_retry:
            try:
                import asyncio
                from app.report_generator import generate_premium_report
                report_data = asyncio.get_event_loop().run_until_complete(
                    generate_premium_report(row["report_type"]))
                with conn.cursor() as cur2:
                    cur2.execute(
                        "UPDATE report_escrows SET status='delivered', report_data=%s, delivered_at=NOW() WHERE id=%s",
                        (json.dumps(report_data), row["id"]))
                logger.info(f"Report {row['id']} generated on retry")
            except Exception as e:
                with conn.cursor() as cur2:
                    cur2.execute("UPDATE report_escrows SET retry_count=retry_count+1, error_message=%s WHERE id=%s",
                                 (str(e)[:200], row["id"]))
        # 2. Expire unfunded reports older than 1h
        with conn.cursor() as cur:
            cur.execute("UPDATE report_escrows SET status='expired' WHERE status='pending' AND created_at < NOW() - INTERVAL '1 hour'")
        # 3. Mark failed (exceeded retries)
        with conn.cursor() as cur:
            cur.execute("UPDATE report_escrows SET status='failed' WHERE status='funded' AND retry_count >= 3")
    except Exception as e:
        logger.warning(f"resolve_report_escrows error: {e}")


def start_scheduler():
    from datetime import datetime, timedelta
    from app.content_engine import run_card_generation_cycle

    # Delay all jobs so uvicorn starts accepting connections immediately
    t = datetime.now()
    scheduler.add_job(run_card_generation_cycle, "interval", minutes=10, id="card_gen", max_instances=1, next_run_time=t + timedelta(seconds=90))
    scheduler.add_job(monitor_positions, "interval", minutes=10, id="position_monitor", max_instances=1, next_run_time=t + timedelta(seconds=30))
    scheduler.add_job(expire_old_cards, 'interval', minutes=10, id='expire_cards', max_instances=1, next_run_time=t + timedelta(seconds=45))
    from app.content_engine import backfill_chart_data
    scheduler.add_job(backfill_chart_data, "interval", minutes=30, id="backfill_charts", max_instances=1, next_run_time=t + timedelta(seconds=120))
    from app.sosovalue_client import refresh_cache as refresh_sosovalue
    scheduler.add_job(refresh_sosovalue, "interval", minutes=10, id="sosovalue_cache", max_instances=1, next_run_time=t + timedelta(seconds=60))
    from app.insight_engine import generate_and_store_insight_cards
    from app.degen_oracle import refresh_oracle
    from app.agent_memory import resolve_predictions, ensure_table as ensure_predictions_table
    from app.lp_advisory import generate_lp_advisories
    ensure_predictions_table()
    scheduler.add_job(generate_and_store_insight_cards, "interval", minutes=30, id="insight_cards", max_instances=1, next_run_time=t + timedelta(seconds=150))
    scheduler.add_job(refresh_oracle, "interval", minutes=30, id="oracle_refresh", max_instances=1, next_run_time=t + timedelta(seconds=40))
    scheduler.add_job(resolve_predictions, "interval", minutes=30, id="resolve_predictions", max_instances=1, next_run_time=t + timedelta(seconds=180))
    scheduler.add_job(generate_lp_advisories, "interval", minutes=15, id="lp_advisory", max_instances=1, next_run_time=t + timedelta(seconds=100))
    from app.agent_runner import run_user_agents, update_agent_preferences
    scheduler.add_job(run_user_agents, "interval", minutes=10, id="user_agents", max_instances=1, next_run_time=t + timedelta(seconds=70))
    scheduler.add_job(update_agent_preferences, "interval", minutes=60, id="agent_learn", max_instances=1, next_run_time=t + timedelta(seconds=200))
    from app.news_aggregator import refresh_news
    from app.sentiment_engine import refresh_sentiment
    scheduler.add_job(refresh_news, "interval", minutes=10, id="news_refresh", max_instances=1, next_run_time=t + timedelta(seconds=50))
    scheduler.add_job(refresh_sentiment, "interval", minutes=10, id="sentiment_refresh", max_instances=1, next_run_time=t + timedelta(seconds=55))
    scheduler.add_job(resolve_expired_escrows, "interval", minutes=30, id="escrow_resolve", max_instances=1, next_run_time=t + timedelta(seconds=210))
    scheduler.add_job(resolve_report_escrows, "interval", minutes=5, id="report_escrow_resolve", max_instances=1, next_run_time=t + timedelta(seconds=120))

    # ── Initia-Native helpers (PRD-Initia-Native-Upgrade) ──
    scheduler.add_job(_chain_ops_reconcile_job, "interval", seconds=60,
                      id="chain_ops_reconciler", max_instances=1,
                      next_run_time=t + timedelta(seconds=20))
    scheduler.add_job(_oracle_resolve_job, "interval", minutes=30,
                      id="oracle_resolve", max_instances=1,
                      next_run_time=t + timedelta(seconds=240))
    scheduler.add_job(_vip_score_update_job, "interval", hours=24,
                      id="vip_score_update", max_instances=1,
                      next_run_time=t + timedelta(seconds=300))
    scheduler.add_job(_vip_finalize_epoch_job, "interval", days=14,
                      id="vip_finalize_epoch", max_instances=1,
                      next_run_time=t + timedelta(seconds=360))
    _start_ibc_listener_thread()

    # ── Gem Scanner ──
    scheduler.add_job(_gem_scan_job, "interval", minutes=30,
                      id="gem_scan", max_instances=1,
                      next_run_time=t + timedelta(seconds=160))

    scheduler.start()
    logger.info("Scheduler started — all jobs delayed for graceful startup")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)



# ═══════════════════════════════════════════════════════════════════════════
# Initia-Native scheduler jobs (PRD-Initia-Native-Upgrade)
#
# Per-job circuit breakers + chain_ops idempotency keep these crash-safe.
# Each job acquires a Postgres advisory lock so two scheduler processes
# (e.g. blue/green deploy) never run the same job concurrently.
# ═══════════════════════════════════════════════════════════════════════════

def _with_advisory_lock(job_id: str, fn):
    """Run fn() iff we can acquire pg_try_advisory_lock(hash(job_id)).

    Lock is auto-released on connection close. Multi-process safe.
    """
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        # No DB — fall through to local execution; deploy guarantees DB exists.
        return fn()
    try:
        # Stable 8-byte int from job id
        lock_key = abs(hash(job_id)) % (2**31)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
            row = cur.fetchone()
            got_lock = bool(row and row[0])
        if not got_lock:
            logger.debug("scheduler[%s] advisory lock held by another process; skipping", job_id)
            return None
        try:
            return fn()
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
    finally:
        conn.close()


def _gem_scan_job():
    """Generate gem cards from scanner."""
    import asyncio
    from app.gem_scanner import scan_for_gems
    from app.db import insert_card

    async def _run():
        gems = await scan_for_gems(limit=5)
        for gem in gems:
            insert_card({
                "token_symbol": gem.symbol,
                "token_name": gem.name,
                "chain": gem.chain,
                "price": gem.price,
                "price_change_24h": gem.price_change_24h,
                "volume_24h": gem.volume_24h,
                "market_cap": gem.market_cap,
                "card_type": "gem",
                "verdict": "APE",
                "risk_score": gem.risk,
                "rarity": "legendary" if gem.gem_score > 85 else "epic" if gem.gem_score > 70 else "rare",
                "hook": f"💎 Gem Score {gem.gem_score}/100",
                "roast": " | ".join(gem.signals),
                "metrics": [{"emoji": s.split(" ")[0], "label": s.split(" ", 1)[1] if " " in s else s, "value": "", "sentiment": "bullish"} for s in gem.signals],
                "status": "active",
            })
        logger.info(f"Gem scan: {len(gems)} gems generated")

    try:
        asyncio.run(_run())
    except Exception as e:
        logger.error(f"Gem scan failed: {e}")


def _chain_ops_reconcile_job():
    """Sweep stuck chain_operations rows. 60s cadence."""
    from app import chain_ops
    def _do():
        try:
            counts = chain_ops.reconcile()
            if any(v for k, v in counts.items() if k != "checked"):
                logger.info("chain_ops reconcile: %s", counts)
        except Exception as e:
            logger.warning("chain_ops reconcile failed: %s", e)
    _with_advisory_lock("chain_ops_reconciler", _do)


def _oracle_resolve_job():
    """Snapshot oracle exit-price for unresolved signals past 24h.

    Read existing signals from DB; for each unresolved + past-24h signal,
    submit a chain_ops 'oracle_exit_price' op pointing at OracleAdapter.
    The reconciler heals retries automatically.
    """
    from app.chain import ChainClient
    from app.db import _get_conn

    def _do():
        conn = _get_conn()
        if not conn:
            return
        try:
            from psycopg2.extras import RealDictCursor
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, symbol FROM signals
                     WHERE resolved = FALSE
                       AND created_at < NOW() - INTERVAL '24 hours'
                     ORDER BY id
                     LIMIT 50
                    """
                )
                rows = cur.fetchall()
        except Exception as e:
            logger.warning("oracle_resolve query failed: %s", e)
            rows = []
        finally:
            conn.close()
        if not rows:
            return
        try:
            chain = ChainClient()
        except Exception as e:
            logger.warning("oracle_resolve: ChainClient init failed: %s", e)
            return
        for r in rows:
            symbol = (r.get("symbol") or "").upper()
            if not symbol:
                continue
            pair = f"{symbol}/USD"
            try:
                chain.commit_exit_price_proof(int(r["id"]), pair)
            except Exception as e:
                logger.debug("oracle_resolve signal=%s pair=%s err=%s", r["id"], pair, e)

    _with_advisory_lock("oracle_resolve", _do)


def _vip_score_update_job():
    """Push the top-N reputation users to VIPScoreAdapter once per day.

    Excludes operator/team addresses per the VIP whitelisting proposal.
    """
    from app.chain import ChainClient
    from app.config import get_settings

    EXCLUDED = {get_settings().__dict__.get("deployer_address", "").lower()} or set()

    def _do():
        try:
            chain = ChainClient()
        except Exception as e:
            logger.warning("vip_score_update: ChainClient init failed: %s", e)
            return
        try:
            leaderboard = chain.get_conviction_leaderboard(0, 200)
        except Exception as e:
            logger.warning("vip_score_update: leaderboard read failed: %s", e)
            return
        users = [
            row["address"] for row in leaderboard
            if row["address"].lower() not in EXCLUDED and row["reputationScore"] > 0
        ]
        if not users:
            return
        # Page in batches of 100 (VIPScoreAdapter.scoreBatch gas-safety).
        for i in range(0, len(users), 100):
            batch = users[i:i + 100]
            try:
                chain.vip_score_batch(batch)
            except Exception as e:
                logger.warning("vip_score_update batch %d failed: %s", i // 100, e)

    _with_advisory_lock("vip_score_update", _do)


def _vip_finalize_epoch_job():
    """Finalize the current VIP epoch every 14 days (aligned with VIP stage)."""
    from app.chain import ChainClient

    def _do():
        try:
            chain = ChainClient()
            chain.vip_finalize_epoch()
        except Exception as e:
            logger.warning("vip_finalize_epoch failed: %s", e)

    _with_advisory_lock("vip_finalize_epoch", _do)


def _start_ibc_listener_thread():
    """Spawn the asyncio IBC listener in a background thread.

    The listener is asyncio-native; we run it in its own event loop on a
    daemon thread so the sync APScheduler stays unaffected.
    """
    import threading
    import asyncio

    def _runner():
        try:
            from app.ibc_listener import run as ibc_run
            asyncio.run(ibc_run())
        except Exception as e:
            logger.warning("ibc_listener thread crashed: %s", e)

    th = threading.Thread(target=_runner, name="ibc_listener", daemon=True)
    th.start()
    logger.info("ibc_listener thread started")
