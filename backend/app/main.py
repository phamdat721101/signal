import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.error_tracker import error_tracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_chain = None


def get_chain():
    global _chain
    if _chain is None:
        from app.chain import ChainClient
        _chain = ChainClient()
    return _chain


# Simple in-memory cache
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 30


def cached(key: str, ttl: int = CACHE_TTL):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]
    return None


def set_cache(key: str, value):
    _cache[key] = (time.time(), value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(f"Starting Initia Signal backend | network={settings.network}")
    from app.signal_engine import bootstrap_price_history
    from app.scheduler import start_scheduler
    if settings.contract_address:
        try:
            get_chain()
            logger.info("Chain client connected")
        except Exception as e:
            logger.warning(f"Chain client init failed: {e}")
    else:
        logger.info("No CONTRACT_ADDRESS — running in simulation mode (in-memory signals)")
    # Init Supabase DB
    if settings.database_url:
        from app.db import init_db
        try:
            init_db()
        except Exception as e:
            logger.warning(f"DB init failed: {e}")
    bootstrap_price_history()
    start_scheduler()
    yield
    from app.scheduler import stop_scheduler
    stop_scheduler()
    logger.info("Shutting down")


app = FastAPI(title="Initia Signal API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _fallback_metadata(signal: dict) -> dict:
    """Compute metadata for old signals that lack it."""
    entry = int(signal.get("entryPrice", 0))
    target = int(signal.get("targetPrice", 0))
    is_bull = signal.get("isBull", True)
    price = entry / 1e18 if entry else 0
    target_price = target / 1e18 if target else 0
    stop_loss = price * 0.985 if is_bull else price * 1.015

    if is_bull:
        pattern = "Golden Cross" if target_price > price else "Bullish Momentum"
    else:
        pattern = "Death Cross" if target_price < price else "Bearish Momentum"

    from app.signal_engine import TRACKED_ASSETS
    asset_addr = signal.get("asset", "").lower()
    symbol = TRACKED_ASSETS.get(asset_addr, TRACKED_ASSETS.get(asset_addr.lower(), "UNKNOWN"))
    direction = "bullish" if is_bull else "bearish"
    action = "BUY" if is_bull else "SELL"

    analysis = (
        f"{action} {symbol} | {pattern} detected on 30-min chart. "
        f"Signal indicates {direction} momentum. "
        f"Entry ${price:,.2f} → Target ${target_price:,.2f} / Stop ${stop_loss:,.2f} (1:1 R:R). "
        f"Confidence {signal.get('confidence', 0)}%. Auto-resolves in 24h."
    )
    return {
        "pattern": pattern,
        "analysis": analysis,
        "timeframe": "30m candles / 24h horizon",
        "stopLoss": str(int(stop_loss * 1e18)),
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    code = "INTERNAL_ERROR"
    message = str(exc)
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": exc.detail}})
    error_tracker.track(code, message)
    return JSONResponse(status_code=500, content={"error": {"code": code, "message": message}})


@app.get("/api/health")
async def health():
    settings = get_settings()
    connected = False
    simulation = not bool(settings.contract_address)
    if not simulation:
        try:
            chain = get_chain()
            connected = chain.w3.is_connected()
        except Exception:
            pass
    return {
        "status": "ok",
        "network": settings.network,
        "rpc_url": settings.json_rpc_url if not simulation else None,
        "contract": settings.contract_address or None,
        "chain_connected": connected,
        "simulation_mode": simulation,
    }


@app.get("/api/errors")
async def get_errors():
    return {"errors": error_tracker.get_recent()}


@app.get("/api/signals")
async def get_signals(offset: int = 0, limit: int = Query(default=100, le=100), provider: str | None = Query(default=None)):
    cache_key = f"signals:{offset}:{limit}:{provider}"
    data = cached(cache_key)
    if data:
        return data
    settings = get_settings()

    # Primary: read from Supabase
    if settings.database_url:
        from app.db import get_signals as db_get_signals
        db_signals, db_total = db_get_signals(offset, limit, provider)
        if db_total > 0 or provider:
            result = {"signals": db_signals, "total": db_total}
            set_cache(cache_key, result)
            return result

    # Fallback: simulation mode
    if not settings.contract_address:
        from app.signal_engine import sim_signals
        result = {"signals": sim_signals[offset:offset + limit], "total": len(sim_signals)}
        set_cache(cache_key, result)
        return result

    # Fallback: on-chain
    try:
        chain = get_chain()
        total = chain.get_signal_count()
        signals = chain.get_signals(offset, limit) if total > 0 else []
        from app.signal_engine import signal_metadata, TRACKED_ASSETS
        for s in signals:
            meta = signal_metadata.get(s["id"])
            if meta:
                s.update(meta)
            elif not s.get("pattern"):
                s.update(_fallback_metadata(s))
            s.setdefault("symbol", TRACKED_ASSETS.get(s["asset"].lower(), ""))
        result = {"signals": signals, "total": total}
        set_cache(cache_key, result)
        return result
    except Exception as e:
        error_tracker.track("SIGNALS_FETCH_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/signals/{signal_id}")
async def get_signal(signal_id: int, source: str = Query(default="auto")):
    settings = get_settings()

    # Primary: Supabase
    if settings.database_url and source in ("db", "auto"):
        from app.db import get_signal_by_id
        db_signal = get_signal_by_id(signal_id)
        if db_signal:
            return db_signal

    # Fallback: simulation mode
    if not settings.contract_address:
        from app.signal_engine import sim_signals
        if 0 <= signal_id < len(sim_signals):
            return sim_signals[signal_id]
        raise HTTPException(status_code=404, detail="Signal not found")

    # Fallback: on-chain
    try:
        chain = get_chain()
        signal = chain.get_signal(signal_id)
        from app.signal_engine import signal_metadata, TRACKED_ASSETS
        meta = signal_metadata.get(signal_id)
        if meta:
            signal.update(meta)
        elif not signal.get("pattern"):
            signal.update(_fallback_metadata(signal))
        signal.setdefault("symbol", TRACKED_ASSETS.get(signal["asset"].lower(), ""))
        return signal
    except Exception as e:
        error_tracker.track("SIGNAL_FETCH_ERROR", str(e), {"signal_id": signal_id})
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/prices")
async def get_prices():
    data = cached("prices", ttl=15)
    if data:
        return data
    from app.signal_engine import get_current_prices, TRACKED_ASSETS
    prices = get_current_prices()
    result = {
        "prices": prices,
        "assets": {addr: sym for addr, sym in TRACKED_ASSETS.items()},
    }
    set_cache("prices", result)
    return result


@app.get("/api/prices/{symbol:path}/history")
async def get_price_history(symbol: str):
    from app.signal_engine import get_price_history_for_asset
    history = get_price_history_for_asset(symbol)
    return {"symbol": symbol, "history": history}




@app.post("/api/signals/generate")
async def trigger_signal_generation(
    request: Request,
    assets: str | None = Query(default=None),
    timeframe: str = Query(default="30m"),
    target_pct: float = Query(default=1.5, ge=0.1, le=20.0),
):
    """Generate signals. Params: ?assets=BTC/USD&timeframe=30m&target_pct=1.5"""
    settings = get_settings()
    payment_info = None
    asset_list = [a.strip() for a in assets.split(",") if a.strip()] if assets else None
    target_decimal = target_pct / 100.0  # convert 1.5 → 0.015

    if settings.enable_payment_gating and settings.session_vault_address:
        tx_hash = request.headers.get("X-PAYMENT-TX")
        if not tx_hash:
            from app.mpp_middleware import SERVICE_PRICING
            verifier = _get_payment_verifier()
            raise HTTPException(status_code=402, detail=verifier.build_402_response(
                "signal-premium", SERVICE_PRICING["signal-premium"]["price_wei"], settings.mock_iusd_address))
        from app.mpp_middleware import SERVICE_PRICING
        verifier = _get_payment_verifier()
        result = verifier.verify_payment_tx(tx_hash, "signal-premium",
                                            SERVICE_PRICING["signal-premium"]["price_wei"])
        if not result["valid"]:
            raise HTTPException(status_code=402, detail={"error": result["error"]})
        payment_info = {"status": "paid", "tx_hash": tx_hash,
                        "session_id": result["session_id"], "amount_paid": str(result["amount"])}

    from app.signal_engine import run_signal_cycle, price_history, recent_signal_txs
    try:
        before = len(recent_signal_txs)
        cycle_result = run_signal_cycle(asset_list, target_decimal, timeframe)
        after = len(recent_signal_txs)
        new_signals = after - before
        history_depth = {k: len(v) for k, v in price_history.items()}
        _cache.clear()
        result = {
            "status": "ok" if cycle_result["success"] else "partial",
            "newSignals": new_signals,
            "priceHistory": history_depth,
            "recentTxs": [t for t in recent_signal_txs[-new_signals:]] if new_signals > 0 else [],
        }
        if cycle_result["errors"]:
            result["errors"] = cycle_result["errors"]
        if payment_info:
            result["payment"] = payment_info
        return result
    except Exception as e:
        error_tracker.track("GENERATE_ENDPOINT_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/signal-options")
async def get_signal_options():
    """Available token pairs, timeframes, and default target %."""
    from app.signal_engine import TRACKED_ASSETS, TIMEFRAMES, DEFAULT_TIMEFRAME, DEFAULT_TARGET_PCT, COINGECKO_IDS
    return {
        "assets": [{"address": addr, "symbol": sym} for addr, sym in TRACKED_ASSETS.items()],
        "availablePairs": sorted(COINGECKO_IDS.keys()),
        "timeframes": [{"value": k, "label": v["label"]} for k, v in TIMEFRAMES.items()],
        "defaults": {
            "timeframe": DEFAULT_TIMEFRAME,
            "targetPct": DEFAULT_TARGET_PCT * 100,
        },
    }


@app.post("/api/assets")
async def add_asset(symbol: str = Query(...)):
    """Add a custom token pair. Example: ?symbol=SOL/USD or ?symbol=SOL"""
    from app.signal_engine import add_tracked_asset, COINGECKO_IDS, bootstrap_price_history
    sym = symbol.upper()
    if not sym.endswith("/USD"):
        sym = f"{sym}/USD"
    if sym not in COINGECKO_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown pair: {sym}. Available: {sorted(COINGECKO_IDS.keys())}")
    addr = add_tracked_asset(sym)
    bootstrap_price_history()
    _cache.clear()
    return {"status": "ok", "symbol": sym, "address": addr}


@app.delete("/api/assets")
async def delete_asset(symbol: str = Query(...)):
    """Remove a token pair from tracking."""
    from app.signal_engine import remove_tracked_asset
    if not remove_tracked_asset(symbol):
        raise HTTPException(status_code=404, detail=f"Asset not found: {symbol}")
    _cache.clear()
    return {"status": "ok", "removed": symbol}


@app.get("/api/report")
async def get_report(address: str | None = Query(default=None)):
    """Performance report. Pass ?address=0x... to filter by user's executed signals."""
    settings = get_settings()
    from app.signal_engine import signal_metadata

    # Simulation mode — build report from in-memory signals
    if not settings.contract_address:
        from app.signal_engine import sim_signals, TRACKED_ASSETS
        import time as _time
        signals = [s for s in sim_signals if not address or s.get("creator", "").lower() == address.lower()]
        resolved = [s for s in signals if s["resolved"]]
        wins, losses = [], []
        per_asset: dict[str, dict] = {}
        balance = 10_000.0
        balance_history = [{"trade": 0, "balance": balance}]
        for s in resolved:
            entry = int(s["entryPrice"])
            exit_ = int(s["exitPrice"])
            pct = ((exit_ - entry) / entry * 100) if entry else 0
            if not s["isBull"]:
                pct = -pct
            profit = 100.0 * (pct / 100)
            balance += profit
            balance_history.append({"trade": len(balance_history), "balance": round(balance, 2)})
            (wins if pct > 0 else losses).append({"id": s["id"], "pct": round(pct, 4)})
            ak = TRACKED_ASSETS.get(s["asset"].lower(), "OTHER").replace("/USD", "")
            if ak not in per_asset:
                per_asset[ak] = {"total": 0, "wins": 0, "losses": 0, "totalPnl": 0.0}
            pa = per_asset[ak]
            pa["total"] += 1
            pa["wins" if pct > 0 else "losses"] += 1
            pa["totalPnl"] = round(pa["totalPnl"] + pct, 4)
        for pa in per_asset.values():
            pa["winRate"] = round((pa["wins"] / pa["total"]) * 100, 1) if pa["total"] > 0 else 0
        all_pcts = [w["pct"] for w in wins] + [l["pct"] for l in losses]
        return {
            "generatedAt": _time.time(), "totalSignals": len(signals), "resolvedSignals": len(resolved),
            "activeSignals": len(signals) - len(resolved), "wins": len(wins), "losses": len(losses),
            "winRate": round((len(wins) / len(resolved)) * 100, 1) if resolved else 0,
            "averageRoi": round(sum(all_pcts) / len(all_pcts), 4) if all_pcts else 0,
            "bestTrade": max(all_pcts) if all_pcts else 0, "worstTrade": min(all_pcts) if all_pcts else 0,
            "perAsset": per_asset, "creator": address,
            "simulation": {"startingBalance": 10000, "tradeSize": 100, "finalBalance": round(balance, 2),
                           "totalReturn": round(balance - 10000, 2),
                           "totalReturnPct": round(((balance - 10000) / 10000) * 100, 2),
                           "balanceHistory": balance_history},
        }

    try:
        from app.report import generate_report
        chain = get_chain()
        report = generate_report(chain, signal_metadata, creator=address)
        return report
    except Exception as e:
        error_tracker.track("REPORT_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/signals/execute")
async def execute_signal_simulated(
    asset: str = Query(...),
    isBull: bool = Query(...),
    confidence: int = Query(...),
    targetPrice: str = Query(...),
    entryPrice: str = Query(...),
    creator: str = Query(default="0x0000000000000000000000000000000000000000"),
):
    """Simulated signal execution — stores in memory, returns fake tx hash."""
    import os
    from app.signal_engine import sim_signals, signal_metadata, recent_signal_txs, MAX_RECENT_TXS, TRACKED_ASSETS
    signal_id = len(sim_signals)
    tx_hash = f"0x{os.urandom(32).hex()}"
    entry_val = int(entryPrice)
    target_val = int(targetPrice)
    price = entry_val / 1e18
    is_bull = isBull
    target_price = target_val / 1e18
    stop_loss = price * 0.985 if is_bull else price * 1.015
    symbol = TRACKED_ASSETS.get(asset.lower(), "UNKNOWN")
    sim_signals.append({
        "id": signal_id, "asset": asset, "isBull": is_bull, "confidence": confidence,
        "targetPrice": targetPrice, "entryPrice": entryPrice, "exitPrice": "0",
        "timestamp": int(time.time()), "resolved": False, "creator": creator, "symbol": symbol,
    })
    recent_signal_txs.append({
        "signalId": signal_id, "txHash": tx_hash, "symbol": symbol,
        "isBull": is_bull, "confidence": confidence, "price": price, "timestamp": time.time(),
    })
    if len(recent_signal_txs) > MAX_RECENT_TXS:
        recent_signal_txs.pop(0)
    _cache.clear()
    return {"status": "ok", "signalId": signal_id, "txHash": tx_hash}


# ─── Card API (Ape or Fade) ──────────────────────────────────

@app.get("/api/cards")
async def get_cards_feed(offset: int = 0, limit: int = Query(default=20, le=50)):
    settings = get_settings()
    if not settings.database_url:
        return {"cards": [], "total": 0}
    from app.db import get_cards
    cards, total = get_cards(offset, limit)
    return {"cards": cards, "total": total}


@app.get("/api/cards/{card_id}")
async def get_card(card_id: int):
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(status_code=404, detail="DB not configured")
    from app.db import get_card_by_id
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@app.post("/api/cards/{card_id}/ape")
async def ape_card(card_id: int, request: Request):
    body = await request.json()
    address = body.get("address", "")
    from app.db import record_swipe, get_card_by_id
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    swipe_id = record_swipe(card_id, address, "ape")
    return {"status": "ok", "swipe_id": swipe_id, "action": "ape", "card": card}


@app.post("/api/cards/{card_id}/fade")
async def fade_card(card_id: int, request: Request):
    body = await request.json()
    address = body.get("address", "")
    from app.db import record_swipe
    swipe_id = record_swipe(card_id, address, "fade")
    return {"status": "ok", "swipe_id": swipe_id, "action": "fade"}


@app.get("/api/cards/user/{address}")
async def get_user_card_history(address: str, offset: int = 0, limit: int = Query(default=50, le=100)):
    from app.db import get_user_swipes
    swipes, total = get_user_swipes(address, offset, limit)
    return {"swipes": swipes, "total": total}


@app.get("/api/leaderboard")
async def get_leaderboard_data():
    from app.db import get_leaderboard
    return {"leaderboard": get_leaderboard()}


@app.post("/api/cards/generate")
async def trigger_card_generation():
    from app.content_engine import run_card_generation_cycle
    try:
        run_card_generation_cycle()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ─── Rewards & Achievements API ──────────────────────────────

@app.get("/api/rewards/{address}")
async def get_user_rewards(address: str):
    """Get reward stats for a user from RewardEngine contract."""
    settings = get_settings()
    if not settings.reward_engine_address:
        # Fallback: compute from swipes
        from app.db import get_user_swipes
        swipes, total = get_user_swipes(address, 0, 1000)
        apes = [s for s in swipes if s.get("action") == "ape"]
        wins = [s for s in apes if (s.get("price_change_24h") or 0) > 0]
        streak = 0
        best_streak = 0
        for s in apes:
            if (s.get("price_change_24h") or 0) > 0:
                streak += 1
                best_streak = max(best_streak, streak)
            else:
                streak = 0
        return {
            "address": address,
            "totalTrades": len(apes),
            "wins": len(wins),
            "winRate": round(len(wins) / len(apes) * 100, 1) if apes else 0,
            "currentStreak": streak,
            "bestStreak": best_streak,
            "pendingRewards": 0,
        }
    try:
        chain = get_chain()
        from web3 import Web3
        import json
        from pathlib import Path
        abi = json.loads((Path(__file__).parent / "reward_engine_abi.json").read_text()) if (Path(__file__).parent / "reward_engine_abi.json").exists() else []
        contract = chain.w3.eth.contract(address=Web3.to_checksum_address(settings.reward_engine_address), abi=abi)
        stats = contract.functions.getStats(Web3.to_checksum_address(address)).call()
        return {
            "address": address, "totalTrades": stats[0], "wins": stats[1],
            "currentStreak": stats[2], "bestStreak": stats[3], "pendingRewards": str(stats[4]),
            "winRate": round(stats[1] / stats[0] * 100, 1) if stats[0] > 0 else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/achievements/{address}")
async def get_user_achievements(address: str):
    """Get achievement tiers for a user."""
    from app.db import get_user_swipes
    swipes, _ = get_user_swipes(address, 0, 1000)
    apes = [s for s in swipes if s.get("action") == "ape"]
    wins = [s for s in apes if (s.get("price_change_24h") or 0) > 0]
    win_count = len(wins)
    win_rate = round(len(wins) / len(apes) * 10000) if apes else 0  # basis points
    streak = 0
    best_streak = 0
    for s in apes:
        if (s.get("price_change_24h") or 0) > 0:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0

    tiers = []
    if win_count >= 10: tiers.append({"tier": "BRONZE_APE", "emoji": "🥉", "name": "Bronze Ape"})
    if win_rate >= 5000 and len(apes) >= 50: tiers.append({"tier": "SILVER_APE", "emoji": "🥈", "name": "Silver Ape"})
    if win_count >= 100: tiers.append({"tier": "GOLD_APE", "emoji": "🥇", "name": "Gold Ape"})
    if best_streak >= 10: tiers.append({"tier": "DIAMOND_HANDS", "emoji": "💎", "name": "Diamond Hands"})
    if win_rate >= 8000 and len(apes) >= 100: tiers.append({"tier": "SIGNAL_SAGE", "emoji": "🧠", "name": "Signal Sage"})

    return {
        "address": address,
        "stats": {"wins": win_count, "winRate": win_rate, "bestStreak": best_streak, "totalTrades": len(apes)},
        "earned": tiers,
        "available": [t for t in ["BRONZE_APE", "SILVER_APE", "GOLD_APE", "DIAMOND_HANDS", "SIGNAL_SAGE"]
                      if t not in [x["tier"] for x in tiers]],
    }


@app.get("/api/contracts")
async def get_contract_addresses():
    """Return all deployed contract addresses."""
    settings = get_settings()
    return {
        "signalRegistry": settings.contract_address or None,
        "mockIUSD": settings.mock_iusd_address or None,
        "sessionVault": settings.session_vault_address or None,
        "paymentGateway": settings.payment_gateway_address or None,
        "rewardEngine": settings.reward_engine_address or None,
        "proofOfAlpha": settings.proof_of_alpha_address or None,
    }


# ─── External Provider API ──────────────────────────────────

from pydantic import BaseModel


class ProviderSignal(BaseModel):
    asset: str
    symbol: str
    isBull: bool
    confidence: int
    targetPrice: str
    entryPrice: str
    provider: str
    pattern: str = ""
    analysis: str = ""
    timeframe: str = ""
    stopLoss: str = "0"
    creator: str = ""


@app.post("/api/provider/signals")
async def provider_submit_signal(signal: ProviderSignal):
    """Public API for external providers to submit trading signals. Stored in Supabase."""
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Database not configured")
    if not signal.provider.strip():
        raise HTTPException(status_code=400, detail="provider is required")
    if signal.confidence < 0 or signal.confidence > 100:
        raise HTTPException(status_code=400, detail="confidence must be 0-100")
    from app.db import insert_signal
    row = signal.model_dump()
    row["timestamp"] = int(time.time())
    row["resolved"] = False
    row["exitPrice"] = "0"
    signal_id = insert_signal(row)
    if signal_id < 0:
        raise HTTPException(status_code=500, detail="Failed to store signal")
    _cache.clear()
    return {"status": "ok", "signalId": signal_id, "provider": signal.provider}


@app.post("/api/provider/signals/batch")
async def provider_submit_batch(signals: list[ProviderSignal]):
    """Batch submit signals from external provider."""
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Database not configured")
    from app.db import insert_signal
    results = []
    for s in signals:
        if not s.provider.strip() or s.confidence < 0 or s.confidence > 100:
            results.append({"status": "error", "detail": "invalid signal"})
            continue
        row = s.model_dump()
        row["timestamp"] = int(time.time())
        row["resolved"] = False
        row["exitPrice"] = "0"
        sid = insert_signal(row)
        results.append({"status": "ok", "signalId": sid, "provider": s.provider})
    _cache.clear()
    return {"status": "ok", "count": len([r for r in results if r["status"] == "ok"]), "results": results}


@app.get("/api/provider/signals")
async def provider_get_signals(
    provider: str = Query(...),
    offset: int = 0,
    limit: int = Query(default=100, le=100),
):
    """Get signals from a specific provider."""
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Database not configured")
    from app.db import get_signals as db_get_signals
    signals, total = db_get_signals(offset, limit, provider)
    return {"signals": signals, "total": total, "provider": provider}


@app.get("/api/tx-history")
async def get_tx_history():
    """Return recent AI signal transaction hashes for explorer tracking."""
    from app.signal_engine import recent_signal_txs
    chain_id = "initia-signal-1"
    scan_base = f"https://scan.testnet.initia.xyz/{chain_id}"
    indexer_base = "http://localhost:8080"
    return {
        "transactions": [
            {
                **tx,
                "scanUrl": f"{scan_base}/txs/{tx['txHash']}",
                "indexerUrl": f"{indexer_base}/indexer/tx/v1/txs/{tx['txHash']}",
            }
            for tx in reversed(recent_signal_txs)
        ],
        "scanBase": scan_base,
        "indexerBase": indexer_base,
    }


@app.post("/api/admin/reset")
async def admin_reset():
    """Clear all in-memory signal state."""
    from app.signal_engine import sim_signals, recent_signal_txs, signal_metadata, price_history
    sim_signals.clear()
    recent_signal_txs.clear()
    signal_metadata.clear()
    price_history.clear()
    _cache.clear()
    logger.info("Admin reset: all in-memory signal data cleared")
    return {"status": "ok", "message": "All in-memory signal data cleared. Restart recommended."}


# ─── Payment-gated endpoints ────────────────────────────────

_payment_verifier = None

def _get_payment_verifier():
    global _payment_verifier
    if _payment_verifier is None:
        from app.mpp_middleware import MPPPaymentVerifier
        import json
        from pathlib import Path
        settings = get_settings()
        chain = get_chain()
        vault_abi_path = Path(__file__).parent / "session_vault_abi.json"
        vault_abi = json.loads(vault_abi_path.read_text()) if vault_abi_path.exists() else []
        _payment_verifier = MPPPaymentVerifier(chain, settings.session_vault_address, vault_abi)
    return _payment_verifier


@app.get("/api/signals/premium")
async def get_premium_signals(request: Request, offset: int = 0, limit: int = Query(default=100, le=100)):
    settings = get_settings()
    if not settings.enable_payment_gating or not settings.session_vault_address:
        return await get_signals(offset, limit)
    tx_hash = request.headers.get("X-PAYMENT-TX")
    if not tx_hash:
        from app.mpp_middleware import SERVICE_PRICING
        verifier = _get_payment_verifier()
        raise HTTPException(status_code=402, detail=verifier.build_402_response(
            "signal-premium", SERVICE_PRICING["signal-premium"]["price_wei"], settings.mock_iusd_address))
    from app.mpp_middleware import SERVICE_PRICING
    verifier = _get_payment_verifier()
    result = verifier.verify_payment_tx(tx_hash, "signal-premium",
                                        SERVICE_PRICING["signal-premium"]["price_wei"])
    if not result["valid"]:
        raise HTTPException(status_code=402, detail={"error": result["error"]})
    try:
        chain = get_chain()
        total = chain.get_signal_count()
        signals = chain.get_signals(offset, limit) if total > 0 else []
        return {"signals": signals, "total": total,
                "payment": {"status": "paid", "tx_hash": tx_hash, "amount_paid": str(result["amount"])}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/signals/single/{signal_id}")
async def get_paid_signal(signal_id: int, request: Request):
    settings = get_settings()
    if not settings.enable_payment_gating or not settings.session_vault_address:
        return await get_signal(signal_id)
    tx_hash = request.headers.get("X-PAYMENT-TX")
    if not tx_hash:
        from app.mpp_middleware import SERVICE_PRICING
        verifier = _get_payment_verifier()
        raise HTTPException(status_code=402, detail=verifier.build_402_response(
            "signal-single", SERVICE_PRICING["signal-single"]["price_wei"], settings.mock_iusd_address))
    from app.mpp_middleware import SERVICE_PRICING
    verifier = _get_payment_verifier()
    result = verifier.verify_payment_tx(tx_hash, "signal-single",
                                        SERVICE_PRICING["signal-single"]["price_wei"])
    if not result["valid"]:
        raise HTTPException(status_code=402, detail={"error": result["error"]})
    try:
        return {"signal": get_chain().get_signal(signal_id),
                "payment": {"status": "paid", "tx_hash": tx_hash, "amount_paid": str(result["amount"])}}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/payment/session/{session_id}")
async def get_session_info(session_id: int):
    try:
        session = _get_payment_verifier().vault.functions.getSession(session_id).call()
        return {"sessionId": session_id, "depositor": session[0], "depositAmount": str(session[1]), "remainingBalance": str(session[2]), "totalRedeemed": str(session[3]), "voucherCount": session[4], "createdAt": session[5], "expiresAt": session[6], "active": session[7]}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/payment/pricing")
async def get_pricing():
    from app.mpp_middleware import SERVICE_PRICING
    settings = get_settings()
    return {"pricing": {k: {"price_iusd": v["price_wei"] / 1e18, "price_wei": str(v["price_wei"]), "description": v["description"]} for k, v in SERVICE_PRICING.items()}, "token": settings.mock_iusd_address, "sessionVault": settings.session_vault_address}


@app.post("/api/payment/faucet")
async def claim_faucet(address: str):
    settings = get_settings()
    if not settings.mock_iusd_address:
        raise HTTPException(status_code=400, detail="MockIUSD not deployed")
    try:
        chain = get_chain()
        import json
        from pathlib import Path
        iusd_abi_path = Path(__file__).parent / "mock_iusd_abi.json"
        iusd_abi = json.loads(iusd_abi_path.read_text()) if iusd_abi_path.exists() else []
        from web3 import Web3
        iusd = chain.w3.eth.contract(address=Web3.to_checksum_address(settings.mock_iusd_address), abi=iusd_abi)
        fn = iusd.functions.mint(Web3.to_checksum_address(address), int(1000 * 1e18))
        receipt = chain._send_tx(fn)
        return {"status": "ok", "amount": "1000", "token": "iUSD", "recipient": address, "txHash": receipt["transactionHash"].hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))