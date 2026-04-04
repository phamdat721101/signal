import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings

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
    logger.info("Shutting down")


app = FastAPI(title="Initia Signal API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        result = {"signals": signals, "total": total}
        set_cache(cache_key, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/signals/{signal_id}")
async def get_signal(signal_id: int):
    try:
        chain = get_chain()
        return chain.get_signal(signal_id)
    except Exception as e:
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


@app.get("/api/leaderboard")
async def get_leaderboard():
    data = cached("leaderboard", ttl=60)
    if data:
        return data
    try:
        chain = get_chain()
        total = chain.get_signal_count()
        if total == 0:
            return {"leaderboard": []}

        signals = chain.get_signals(0, min(total, 500))

        # Group by creator
        creators: dict[str, dict] = {}
        for s in signals:
            addr = s["creator"]
            if addr not in creators:
                creators[addr] = {"address": addr, "total": 0, "wins": 0, "pnl": 0}
            creators[addr]["total"] += 1
            if s["resolved"]:
                entry = int(s["entryPrice"])
                exit_ = int(s["exitPrice"])
                if entry > 0:
                    pnl_pct = ((exit_ - entry) / entry) * 100
                    if not s["isBull"]:
                        pnl_pct = -pnl_pct
                    creators[addr]["pnl"] += pnl_pct
                    if pnl_pct > 0:
                        creators[addr]["wins"] += 1

        # Build leaderboard
        board = []
        for addr, stats in creators.items():
            resolved = sum(1 for s in signals if s["creator"] == addr and s["resolved"])
            win_rate = (stats["wins"] / resolved * 100) if resolved > 0 else 0
            board.append({
                "address": addr,
                "totalSignals": stats["total"],
                "resolvedSignals": resolved,
                "wins": stats["wins"],
                "winRate": round(win_rate, 1),
                "totalPnl": round(stats["pnl"], 2),
            })

        board.sort(key=lambda x: x["totalPnl"], reverse=True)
        for i, entry in enumerate(board):
            entry["rank"] = i + 1

        result = {"leaderboard": board}
        set_cache("leaderboard", result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/signals/generate")
async def trigger_signal_generation():
    from app.signal_engine import run_signal_cycle, price_history, recent_signal_txs
    try:
        before = len(recent_signal_txs)
        run_signal_cycle()
        after = len(recent_signal_txs)
        new_signals = after - before
        history_depth = {k: len(v) for k, v in price_history.items()}
        _cache.clear()
        return {
            "status": "ok",
            "newSignals": new_signals,
            "priceHistory": history_depth,
            "recentTxs": [t for t in recent_signal_txs[-new_signals:]] if new_signals > 0 else [],
        }
    except Exception as e:
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
