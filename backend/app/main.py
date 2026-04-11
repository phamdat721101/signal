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
    if settings.contract_address:
        try:
            get_chain()
            logger.info("Chain client connected")
            from app.scheduler import start_scheduler
            from app.signal_engine import bootstrap_price_history
            bootstrap_price_history()
            start_scheduler()
        except Exception as e:
            logger.warning(f"Chain client init failed: {e}")
    else:
        logger.warning("CONTRACT_ADDRESS not set — running in API-only mode")
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
    try:
        chain = get_chain()
        connected = chain.w3.is_connected()
    except Exception:
        pass
    return {
        "status": "ok",
        "network": settings.network,
        "rpc_url": settings.json_rpc_url,
        "contract": settings.contract_address,
        "chain_connected": connected,
    }


@app.get("/api/errors")
async def get_errors():
    return {"errors": error_tracker.get_recent()}


@app.get("/api/signals")
async def get_signals(offset: int = 0, limit: int = Query(default=100, le=100)):
    cache_key = f"signals:{offset}:{limit}"
    data = cached(cache_key)
    if data:
        return data
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
async def get_signal(signal_id: int):
    try:
        chain = get_chain()
        signal = chain.get_signal(signal_id)
        from app.signal_engine import signal_metadata, TRACKED_ASSETS
        meta = signal_metadata.get(signal_id)
        if meta:
            signal.update(meta)
        elif not signal.get("pattern"):
            signal.update(_fallback_metadata(signal))
        # Always include symbol for frontend display
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
    try:
        from app.report import generate_report
        chain = get_chain()
        from app.signal_engine import signal_metadata
        report = generate_report(chain, signal_metadata, creator=address)
        return report
    except Exception as e:
        error_tracker.track("REPORT_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


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