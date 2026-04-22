"""Scheduler — runs card generation + signal resolution + position monitoring."""
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
            return

    now = time.time()
    updated = 0
    for t in trades:
        sym = t["token_symbol"]
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
                settings = get_settings()
                if settings.contract_address and settings.reward_engine_address:
                    from app.chain import ChainClient
                    chain = ChainClient()
                    was_profit = pnl_usd > 0
                    chain.on_trade_resolved(t["user_address"], was_profit, int(t["amount_usd"] * 1e18))
                    # Task 4: Check achievements
                    _check_achievements(chain, t["user_address"])
            except Exception as e:
                logger.warning(f"RewardEngine call failed for trade {t['id']}: {e}")

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


def start_scheduler():
    from app.content_engine import run_card_generation_cycle
    from app.signal_engine import run_signal_cycle, resolve_all_signals

    scheduler.add_job(run_card_generation_cycle, "interval", minutes=5, id="card_gen", max_instances=1)
    scheduler.add_job(monitor_positions, "interval", minutes=5, id="position_monitor", max_instances=1)
    scheduler.add_job(lambda: run_signal_cycle(), "cron", hour="8,14,20", id="signal_cycle", max_instances=1)
    scheduler.add_job(resolve_all_signals, "cron", hour=23, minute=55, id="resolve_signals", max_instances=1)
    scheduler.add_job(expire_old_cards, 'interval', minutes=10, id='expire_cards', max_instances=1)
    from app.content_engine import backfill_chart_data
    scheduler.add_job(backfill_chart_data, "interval", minutes=30, id="backfill_charts", max_instances=1)
    scheduler.start()
    logger.info("Scheduler started: card_gen(5m) + position_monitor(5m) + signal_cycle(3x/day) + resolve(23:55) + expire_cards(10m) + backfill_charts(30m)")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
