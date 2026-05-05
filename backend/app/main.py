import json
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.error_tracker import error_tracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_BECH32_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'

def normalize_address(addr: str) -> str:
    """Convert bech32 (init1...) or hex (0x...) address to checksummed 0x hex. Returns '' for empty."""
    if not addr:
        return ''
    if addr.startswith('0x') or addr.startswith('0X'):
        from web3 import Web3
        return Web3.to_checksum_address(addr)
    # bech32 decode
    pos = addr.rfind('1')
    if pos < 1:
        return addr
    data_part = addr[pos + 1:]
    words = [_BECH32_CHARSET.index(c) for c in data_part[:-6]]
    bits, value, out = 0, 0, []
    for w in words:
        value = (value << 5) | w
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((value >> bits) & 0xff)
    from web3 import Web3
    return Web3.to_checksum_address('0x' + bytes(out).hex())

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
    # Seed cards on startup if feed is empty
    if settings.database_url:
        try:
            from app.db import get_cards
            cards, _ = get_cards(0, 3)
            if len(cards) < 3:
                logger.info("Feed has < 3 cards — seeding on startup...")
                from app.content_engine import run_card_generation_cycle
                run_card_generation_cycle()
                cards2, _ = get_cards(0, 3)
                logger.info(f"Seeded {len(cards2)} cards on startup")
        except Exception as e:
            logger.warning(f"Startup card seed failed (non-fatal): {e}")
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
async def get_errors(code: str | None = Query(default=None)):
    if code:
        return {"errors": error_tracker.get_by_code(code)}
    return {"errors": error_tracker.get_recent(), "summary": error_tracker.summary()}


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
        from app.x402_payment import require_payment
        from app.mpp_middleware import SERVICE_PRICING
        payment_info = await require_payment(
            request, "signal-premium", "$0.01", SERVICE_PRICING["signal-premium"]["price_wei"]
        )

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




@app.get("/api/cards/{card_id}/image")
async def get_card_image(card_id: int):
    from app.db import get_card_by_id
    from app.content_engine import generate_card_svg
    from fastapi.responses import Response
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    try:
        svg = generate_card_svg(card)
    except Exception as e:
        error_tracker.track("SVG_GENERATION_ERROR", str(e), {"card_id": card_id, "symbol": card.get("token_symbol")})
        raise HTTPException(status_code=500, detail=f"SVG generation failed: {e}")
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})

def _is_premium(address: str) -> bool:
    """Check if user has an active SessionVault session (premium)."""
    address = normalize_address(address)
    if not address:
        return False
    settings = get_settings()
    if not settings.session_vault_address or not settings.contract_address:
        return False
    try:
        chain = get_chain()
        from web3 import Web3
        import json
        from pathlib import Path
        vault_abi = json.loads((Path(__file__).parent / "session_vault_abi.json").read_text())
        vault = chain.w3.eth.contract(address=Web3.to_checksum_address(settings.session_vault_address), abi=vault_abi)
        session_ids = vault.functions.getUserSessions(Web3.to_checksum_address(address)).call()
        for sid in reversed(session_ids):
            s = vault.functions.getSession(sid).call()
            if s[7] and s[2] > 0:  # active=True and remainingBalance > 0
                return True
        return False
    except Exception as e:
        logger.warning(f"_is_premium chain check failed for {address}: {e}")
        return True  # fail-open: don't block users when chain is unreachable


@app.post("/api/cards/{card_id}/ape")
async def ape_card(card_id: int, request: Request):
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    amount_usd = float(body.get("amount_usd", 1.0))
    tx_hash = body.get("tx_hash", "")
    from app.db import record_swipe, get_card_by_id, insert_trade
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    price = card.get("price", 0)
    if price <= 0:
        raise HTTPException(status_code=400, detail="Card has no valid price")
    token_amount = amount_usd / price
    on_chain = bool(tx_hash)
    if not tx_hash:
        import os
        tx_hash = f"0x{os.urandom(32).hex()}"
    trade_id = insert_trade({
        "card_id": card_id, "user_address": address,
        "token_symbol": card["token_symbol"], "token_name": card.get("token_name", ""),
        "entry_price": price, "amount_usd": amount_usd,
        "token_amount": token_amount, "tx_hash": tx_hash,
    })
    record_swipe(card_id, address, "ape")
    explorer_url = f"https://scan.testnet.initia.xyz/initia-signal-1/evm-txs/{tx_hash}" if on_chain else None

    # ── ConvictionEngine: commit on-chain conviction ──
    conviction_data = None
    try:
        settings = get_settings()
        if settings.conviction_engine_address and address:
            import hashlib
            card_json = json.dumps({"id": card_id, "symbol": card["token_symbol"],
                                    "hook": card.get("hook", ""), "verdict": card.get("verdict", "")}, sort_keys=True)
            card_hash = bytes.fromhex(hashlib.sha256(card_json.encode()).hexdigest())
            score = min(99, max(1, card.get("risk_score", 70)))
            is_bull = card.get("verdict", "APE") == "APE"
            chain = get_chain()
            cid, ctx = chain.commit_conviction(card_hash, score, is_bull)
            conviction_data = {"id": cid, "score": score, "tx_hash": ctx}
    except Exception as e:
        logger.warning(f"Conviction commit failed (non-fatal): {e}")

    return {
        "status": "ok", "action": "ape",
        "trade": {
            "id": trade_id, "token_symbol": card["token_symbol"],
            "entry_price": price, "amount_usd": amount_usd,
            "token_amount": round(token_amount, 6),
            "tx_hash": tx_hash, "explorer_url": explorer_url,
            "on_chain": on_chain, "trade_type": "futures" if on_chain else "paper",
        },
        "conviction": conviction_data,
    }


@app.post("/api/cards/{card_id}/fade")
async def fade_card(card_id: int, request: Request):
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    from app.db import record_swipe
    swipe_id = record_swipe(card_id, address, "fade")
    return {"status": "ok", "swipe_id": swipe_id, "action": "fade"}


@app.get("/api/cards/user/{address}")
async def get_user_card_history(address: str, offset: int = 0, limit: int = Query(default=50, le=100)):
    address = normalize_address(address)
    from app.db import get_user_swipes
    swipes, total = get_user_swipes(address, offset, limit)
    return {"swipes": swipes, "total": total}




@app.get("/api/trades/{address}")
async def get_user_trades_endpoint(address: str, offset: int = 0, limit: int = Query(default=50, le=100)):
    address = normalize_address(address)
    from app.db import get_user_trades
    trades, total = get_user_trades(address, offset, limit)
    resolved = [t for t in trades if t.get("resolved")]
    summary = {
        "total_invested": sum(t.get("amount_usd", 0) for t in trades),
        "total_pnl_usd": round(sum(t.get("pnl_usd", 0) or 0 for t in trades), 2),
        "total_pnl_pct": 0,
        "win_count": sum(1 for t in resolved if (t.get("pnl_usd") or 0) > 0),
        "loss_count": sum(1 for t in resolved if (t.get("pnl_usd") or 0) <= 0),
        "total_trades": total,
    }
    invested = summary["total_invested"]
    if invested > 0:
        summary["total_pnl_pct"] = round(summary["total_pnl_usd"] / invested * 100, 2)
    return {"trades": trades, "total": total, "summary": summary}

# Username cache for .init resolution
_username_cache: dict[str, tuple[float, str]] = {}

async def _resolve_init_username(address: str) -> str:
    entry = _username_cache.get(address)
    if entry and time.time() - entry[0] < 3600:
        return entry[1]
    try:
        import httpx
        resp = await httpx.AsyncClient().get(
            f"https://indexer.initia.xyz/indexer/username/v1/addresses/{address}",
            timeout=3,
        )
        if resp.status_code == 200:
            data = resp.json()
            username = data.get("username", "")
            if username:
                _username_cache[address] = (time.time(), username)
                return username
    except Exception:
        pass
    _username_cache[address] = (time.time(), "")
    return ""

@app.get("/api/trades/{address}/resolved-recent")
async def get_resolved_recent(address: str):
    address = normalize_address(address)
    from app.db import get_recently_resolved_trades
    return {"trades": get_recently_resolved_trades(address)}


@app.get("/api/metrics")
async def get_metrics():
    """Appchain metrics for VIP application."""
    settings = get_settings()
    metrics = {"signals": 0, "cards": 0, "swipes": 0, "trades": 0, "unique_users": 0}
    if settings.database_url:
        from app.db import _get_conn
        conn = _get_conn()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM signals")
                metrics["signals"] = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM cards")
                metrics["cards"] = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM swipes")
                metrics["swipes"] = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM trades")
                metrics["trades"] = cur.fetchone()[0]
                cur.execute("SELECT COUNT(DISTINCT user_address) FROM swipes")
                metrics["unique_users"] = cur.fetchone()[0]
    metrics["total_transactions"] = metrics["signals"] + metrics["swipes"] + metrics["trades"]
    return metrics


@app.post("/api/cards/generate")
async def trigger_card_generation():
    from app.content_engine import run_card_generation_cycle
    try:
        run_card_generation_cycle()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ─── Rewards & Achievements API ──────────────────────────────

@app.get("/api/profile/{address}")
async def get_profile(address: str):
    """Aggregated profile: rewards + achievements + trades + trading IQ."""
    address = normalize_address(address)
    rewards_data = await get_user_rewards(address)
    achievements_data = await get_user_achievements(address)
    from app.db import get_user_trades
    trades, trade_total = get_user_trades(address, 0, 50)
    resolved = [t for t in trades if t.get("resolved")]
    trades_data = {"summary": {
        "total_invested": sum(t.get("amount_usd", 0) for t in trades),
        "total_pnl_usd": round(sum(t.get("pnl_usd", 0) or 0 for t in trades), 2),
        "total_trades": trade_total,
        "win_count": sum(1 for t in resolved if (t.get("pnl_usd") or 0) > 0),
    }}
    wins = rewards_data.get("wins", 0)
    total = rewards_data.get("totalTrades", 0)
    streak = rewards_data.get("bestStreak", 0)
    earned = len(achievements_data.get("earned", []))
    # On-chain conviction reputation
    conviction_data = {}
    try:
        chain = get_chain()
        conviction_data = chain.get_reputation(address)
    except Exception:
        pass
    on_chain_rep = conviction_data.get("reputationScore", 0)
    iq = max(0, wins * 10 - (total - wins) * 5 + streak * 5 + earned * 25 + (on_chain_rep // 10))
    return {
        "address": address,
        "trading_iq": iq,
        "rewards": rewards_data,
        "achievements": achievements_data,
        "summary": trades_data.get("summary", {}),
        "conviction": {
            "reputation_score": conviction_data.get("reputationScore", 0),
            "total_convictions": conviction_data.get("totalConvictions", 0),
            "correct_calls": conviction_data.get("correctCalls", 0),
            "current_streak": conviction_data.get("currentStreak", 0),
            "best_streak": conviction_data.get("bestStreak", 0),
            "source": "on-chain" if conviction_data else "none",
        },
    }


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
        logger.warning(f"RewardEngine call failed, using fallback: {e}")
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


# ─── Conviction Engine API ──────────────────────────

@app.get("/api/conviction/{address}")
async def get_user_conviction(address: str):
    """Get on-chain reputation from ConvictionEngine."""
    address = normalize_address(address)
    try:
        chain = get_chain()
        rep = chain.get_reputation(address)
        total = rep["totalConvictions"]
        return {
            "address": address,
            "reputation_score": rep["reputationScore"],
            "total_convictions": total,
            "correct_calls": rep["correctCalls"],
            "accuracy": round(rep["correctCalls"] / total * 100, 1) if total > 0 else 0,
            "avg_conviction": round(rep["totalConvictionPoints"] / total, 1) if total > 0 else 0,
            "current_streak": rep["currentStreak"],
            "best_streak": rep["bestStreak"],
            "source": "on-chain",
        }
    except Exception as e:
        logger.warning(f"ConvictionEngine read failed: {e}")
        return {"address": address, "reputation_score": 0, "total_convictions": 0,
                "accuracy": 0, "source": "fallback"}





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
    # Auto-generate card from signal
    card_id = -1
    try:
        from app.content_engine import generate_card_from_signal
        card_id = generate_card_from_signal(signal_id)
    except Exception as e:
        logger.warning(f"Card generation from signal #{signal_id} failed (non-fatal): {e}")
    _cache.clear()
    return {"status": "ok", "signalId": signal_id, "cardId": card_id, "provider": signal.provider}


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


@app.get("/api/provider/{provider_name}/stats")
async def get_provider_stats_endpoint(provider_name: str):
    """Get aggregated stats for a signal provider."""
    from app.db import get_provider_stats
    stats = get_provider_stats(provider_name)
    return {"provider": provider_name, **stats}


@app.get("/api/providers/leaderboard")
async def get_providers_leaderboard(limit: int = Query(default=20, le=50)):
    """Rank signal providers by win rate (min 5 signals)."""
    from app.db import get_provider_leaderboard
    return {"leaderboard": get_provider_leaderboard(limit)}


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
    if not settings.enable_payment_gating:
        return await get_signals(offset, limit)
    from app.x402_payment import require_payment
    from app.mpp_middleware import SERVICE_PRICING
    payment = await require_payment(request, "signal-premium", "$0.01", SERVICE_PRICING["signal-premium"]["price_wei"])
    try:
        if settings.database_url:
            from app.db import get_signals as db_get_signals
            db_signals, db_total = db_get_signals(offset, limit)
            return {"signals": db_signals, "total": db_total, "payment": payment}
        chain = get_chain()
        total = chain.get_signal_count()
        signals = chain.get_signals(offset, limit) if total > 0 else []
        return {"signals": signals, "total": total, "payment": payment}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/signals/single/{signal_id}")
async def get_paid_signal(signal_id: int, request: Request):
    settings = get_settings()
    if not settings.enable_payment_gating:
        return await get_signal(signal_id)
    from app.x402_payment import require_payment
    from app.mpp_middleware import SERVICE_PRICING
    payment = await require_payment(request, "signal-single", "$0.002", SERVICE_PRICING["signal-single"]["price_wei"])
    try:
        if settings.database_url:
            from app.db import get_signal_by_id
            db_signal = get_signal_by_id(signal_id)
            if db_signal:
                return {"signal": db_signal, "payment": payment}
        return {"signal": get_chain().get_signal(signal_id), "payment": payment}
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
    from app.x402_payment import build_x402_info
    settings = get_settings()
    result = {
        "pricing": {k: {"price_iusd": v["price_wei"] / 1e18, "price_wei": str(v["price_wei"]), "description": v["description"]} for k, v in SERVICE_PRICING.items()},
        "token": settings.mock_iusd_address,
        "sessionVault": settings.session_vault_address,
    }
    x402_info = build_x402_info("$0.01")
    if x402_info:
        result["x402"] = x402_info["x402"]
    return result


@app.post("/api/payment/faucet")
async def claim_faucet(address: str):
    address = normalize_address(address)
    if not address:
        raise HTTPException(status_code=400, detail="Invalid address")
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


@app.post("/api/faucet/gas")
async def gas_faucet(address: str):
    """Send native gas tokens to new user from gas-station account."""
    address = normalize_address(address)
    if not address:
        raise HTTPException(status_code=400, detail="Invalid address")
    try:
        chain = get_chain()
        from web3 import Web3
        to = Web3.to_checksum_address(address)
        bal = chain.w3.eth.get_balance(to)
        if bal > Web3.to_wei(0.1, 'ether'):
            return {"status": "ok", "message": "Already funded", "balance": str(bal)}
        tx = {
            "from": chain.account.address, "to": to,
            "value": Web3.to_wei(1, 'ether'), "gas": 21000, "gasPrice": 0,
            "nonce": chain.w3.eth.get_transaction_count(chain.account.address),
        }
        signed = chain.account.sign_transaction(tx)
        tx_hash = chain.w3.eth.send_raw_transaction(signed.raw_transaction)
        chain.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {"status": "ok", "txHash": tx_hash.hex(), "amount": "1 INIT"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Agent Discovery ────────────────────────────────────────

@app.get("/SKILL.md", response_class=PlainTextResponse)
async def skill_md():
    """Agent skill description for paid trading signal detail access."""
    return """---
name: initia-signal-explorer
description: Pay to access detailed AI trading signals with entry/target/stop prices, analysis, chart patterns, and on-chain proof. Free signal summaries available without payment.
metadata:
  version: 1
---

# Initia Signal Explorer

## When to use
- User wants trading signal details (entry price, target, stop loss, analysis)
- User asks about crypto market signals or trading opportunities
- User wants to verify on-chain signal proof

## Base URL
Use the server URL you fetched this SKILL.md from.

## Free Routes (no payment needed)

### `GET /api/signals`
List all signals with summaries. Returns: id, asset, symbol, is_bull, confidence, timeframe, timestamp, resolved.

### `GET /api/signals/{id}`
Get one signal summary by ID.

### `GET /api/payment/pricing`
Get current pricing for paid access including x402 and MPP payment info.

## Paid Routes

### `GET /api/signals/single/{id}` — $0.002
Full signal detail: entry price, target price, stop loss, analysis, chart patterns, risk score, on-chain tx hash.

### `GET /api/signals/premium` — $0.01
Batch: all signals with full details. Supports `?offset=0&limit=100`.

## Payment
Paid routes return HTTP `402` with payment instructions. Two protocols accepted:

### x402 (Base/USDC) — recommended
Standard x402 flow. Agent receives 402 with payment details, signs USDC payment, retries with `PAYMENT-SIGNATURE` header.

### MPP (Initia SessionVault)
Send `X-PAYMENT-TX` header with a tx hash containing a `ServicePaid` event from the Initia SessionVault.

## Recommended Flow
1. Call `GET /api/signals` to browse available signals
2. Pick a signal ID of interest
3. Call `GET /api/signals/single/{id}` — receive 402 with payment details
4. Pay via x402 or MPP
5. Retry the request with payment proof header

## Examples
```bash
# Free: list signals
curl https://your-server/api/signals

# Paid: get signal detail (will return 402 first)
curl https://your-server/api/signals/single/42
```
"""


# ─── Oracle Endpoints ───────────────────────────────────────
@app.get("/api/oracle/mood")
def get_oracle_mood():
    from app.degen_oracle import get_current_mood
    return get_current_mood()

@app.get("/api/oracle/takes")
def get_oracle_takes():
    from app.degen_oracle import get_recent_takes
    return get_recent_takes(5)

# ─── Challenge Endpoints ────────────────────────────────────
@app.get("/api/challenges")
def list_challenges():
    from app.challenges import get_active_challenges
    return {"challenges": get_active_challenges()}

@app.post("/api/challenges/{challenge_id}/enter")
def enter_challenge_endpoint(challenge_id: int, body: dict):
    from app.challenges import enter_challenge
    return enter_challenge(challenge_id, body.get("user_address", ""), body.get("answer", ""))

@app.get("/api/challenges/leaderboard")
def challenge_leaderboard():
    from app.challenges import get_challenge_leaderboard
    return {"leaderboard": get_challenge_leaderboard()}

# ─── Share Endpoint ─────────────────────────────────────────
@app.post("/api/share/generate")
def generate_share(body: dict):
    from app.share_engine import generate_share_card
    return generate_share_card(body.get("trade", {}), body.get("user_address", ""))

# ─── Index Cards Endpoint ───────────────────────────────────
@app.get("/api/indices")
def get_index_cards():
    from app.content_engine import generate_index_cards
    return {"cards": generate_index_cards()}


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    """Machine-readable service description for LLM agent discovery."""
    return """# Initia Signal Explorer
> AI trading signal service with on-chain proof. Pay per signal detail via x402 (Base/USDC) or MPP (Initia).

- Skill: /SKILL.md
- Pricing: /api/payment/pricing

## Free endpoints
- `GET /api/signals` — signal summaries (id, asset, direction, confidence)
- `GET /api/signals/{id}` — single signal summary
- `GET /api/health` — service health check

## Paid endpoints (402 gated)
- `GET /api/signals/single/{id}` — full signal detail ($0.002)
- `GET /api/signals/premium` — batch full details ($0.01)

## Payment protocols
- x402: PAYMENT-SIGNATURE header (Base USDC)
- MPP: X-PAYMENT-TX header (Initia SessionVault)

## Agent flow
1. GET /api/signals → pick signal ID
2. GET /api/signals/single/{id} → 402 with payment info
3. Pay via x402 or MPP → retry with payment header
"""
