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


def resolve_provider_signals():
    """Check provider signals for TP/SL hits. First-hit-wins."""
    from app.db import get_unresolved_provider_signals, resolve_signal_with_type
    from app.signal_engine import COINGECKO_IDS

    signals = get_unresolved_provider_signals()
    if not signals:
        return

    # Collect unique symbols → CoinGecko IDs
    cg_map = {}
    for s in signals:
        sym = (s.get("symbol", "") or s.get("asset", "").replace("/USD", "")).upper()
        key = f"{sym}/USD"
        if key in COINGECKO_IDS:
            cg_map[sym] = COINGECKO_IDS[key]

    if not cg_map:
        return

    # Fetch prices
    prices = {}
    try:
        import httpx
        ids_str = ",".join(cg_map.values())
        resp = httpx.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": ids_str, "vs_currencies": "usd"}, timeout=10)
        if resp.status_code == 200:
            id_to_sym = {v: k for k, v in cg_map.items()}
            for cg_id, vals in resp.json().items():
                if cg_id in id_to_sym and "usd" in vals:
                    prices[id_to_sym[cg_id]] = vals["usd"]
    except Exception as e:
        logger.warning(f"Provider signal price fetch failed: {e}")
        return

    if not prices:
        return

    resolved_count = 0
    for s in signals:
        sym = (s.get("symbol", "") or s.get("asset", "").replace("/USD", "")).upper()
        current_price = prices.get(sym)
        if current_price is None:
            continue

        try:
            entry = float(s["entryPrice"])
            target = float(s["targetPrice"])
            stop_loss = float(s["stopLoss"])
        except (ValueError, TypeError):
            continue
        if entry <= 0 or target <= 0 or stop_loss <= 0:
            continue

        resolution = None
        if s["isBull"]:
            if current_price >= target:
                resolution = "TP_HIT"
            elif current_price <= stop_loss:
                resolution = "SL_HIT"
        else:
            if current_price <= target:
                resolution = "TP_HIT"
            elif current_price >= stop_loss:
                resolution = "SL_HIT"

        if resolution:
            resolve_signal_with_type(s["id"], str(current_price), resolution)
            resolved_count += 1
            logger.info(f"Provider signal #{s['id']} {sym} resolved: {resolution} at ${current_price}")

    if resolved_count:
        logger.info(f"Provider signal resolution: {resolved_count}/{len(signals)} resolved")


def start_scheduler():
    from app.content_engine import run_card_generation_cycle
    from app.signal_engine import run_signal_cycle, resolve_all_signals, run_sosovalue_signal_cycle

    scheduler.add_job(run_card_generation_cycle, "interval", minutes=5, id="card_gen", max_instances=1)
    scheduler.add_job(monitor_positions, "interval", minutes=5, id="position_monitor", max_instances=1)
    scheduler.add_job(lambda: run_signal_cycle(), "cron", hour="8,14,20", id="signal_cycle", max_instances=1)
    scheduler.add_job(resolve_all_signals, "cron", hour=23, minute=55, id="resolve_signals", max_instances=1)
    scheduler.add_job(expire_old_cards, 'interval', minutes=10, id='expire_cards', max_instances=1)
    scheduler.add_job(resolve_provider_signals, "interval", minutes=5, id="provider_resolution", max_instances=1)
    scheduler.add_job(run_sosovalue_signal_cycle, "interval", minutes=30, id="sosovalue_signals", max_instances=1)
    from app.content_engine import backfill_chart_data
    scheduler.add_job(backfill_chart_data, "interval", minutes=30, id="backfill_charts", max_instances=1)
    from app.sosovalue_client import refresh_cache as refresh_sosovalue
    scheduler.add_job(refresh_sosovalue, "interval", minutes=5, id="sosovalue_cache", max_instances=1)
    from app.insight_engine import generate_and_store_insight_cards
    from app.degen_oracle import refresh_oracle
    from app.challenges import generate_daily_challenges, resolve_challenges
    scheduler.add_job(generate_and_store_insight_cards, "interval", minutes=30, id="insight_cards", max_instances=1)
    scheduler.add_job(refresh_oracle, "interval", minutes=30, id="oracle_refresh", max_instances=1)
    scheduler.add_job(generate_daily_challenges, "cron", hour=0, minute=5, id="daily_challenges", max_instances=1)
    scheduler.add_job(resolve_challenges, "cron", hour=23, minute=55, id="resolve_challenges", max_instances=1)
    scheduler.start()
    logger.info("Scheduler started: card_gen(5m) + position_monitor(5m) + signal_cycle(3x/day) + resolve(23:55) + expire_cards(10m) + provider_resolution(5m) + sosovalue_signals(30m) + backfill_charts(30m) + sosovalue_cache(5m) + insight_cards(30m) + oracle_refresh(30m) + daily_challenges(00:05) + resolve_challenges(23:55)")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
