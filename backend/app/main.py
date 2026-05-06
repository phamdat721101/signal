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
    # SoDex real execution
    sodex_order_id = None
    execution_type = "simulated"
    settings = get_settings()
    if settings.sodex_enabled and body.get("execute_real"):
        try:
            from app.sodex_client import place_market_order, map_symbol
            sodex_symbol = map_symbol(card["token_symbol"])
            order = place_market_order(sodex_symbol, "buy", amount_usd)
            sodex_order_id = order.get("order_id")
            execution_type = "sodex"
            if order.get("filled_price"):
                token_amount = amount_usd / order["filled_price"]
        except Exception as e:
            logger.warning(f"SoDex order failed, falling back to simulated: {e}")
    trade_id = insert_trade({
        "card_id": card_id, "user_address": address,
        "token_symbol": card["token_symbol"], "token_name": card.get("token_name", ""),
        "entry_price": price, "amount_usd": amount_usd,
        "token_amount": token_amount, "tx_hash": tx_hash,
    })
    # Store SoDex metadata
    if sodex_order_id:
        from app.db import _get_conn
        conn = _get_conn()
        if conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE trades SET sodex_order_id=%s, execution_type=%s WHERE id=%s",
                            (sodex_order_id, execution_type, trade_id))
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


# ─── SoDex Endpoints ────────────────────────────────────────

@app.get("/api/sodex/symbols")
async def sodex_symbols():
    from app.sodex_client import get_symbols
    try:
        return {"symbols": get_symbols()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/sodex/balance/{address}")
async def sodex_balance(address: str):
    from app.sodex_client import get_balances
    try:
        return get_balances(address)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Provider Marketplace Endpoints ─────────────────────────

@app.post("/api/providers/register")
async def register_provider(request: Request):
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    if not address:
        raise HTTPException(status_code=400, detail="address required")
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO providers (address, name, description, avatar_url)
               VALUES (%s,%s,%s,%s) ON CONFLICT (address) DO UPDATE
               SET name=EXCLUDED.name, description=EXCLUDED.description, avatar_url=EXCLUDED.avatar_url""",
            (address, body.get("name", ""), body.get("description", ""), body.get("avatar_url", "")))
    return {"status": "ok", "address": address}


@app.get("/api/providers/{address}")
async def get_provider_profile(address: str):
    address = normalize_address(address)
    from app.db import _get_conn, get_provider_stats
    conn = _get_conn()
    if not conn:
        return {"address": address, "stats": get_provider_stats(address)}
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM providers WHERE address = %s", (address,))
        row = cur.fetchone()
    profile = dict(row) if row else {"address": address}
    profile["stats"] = get_provider_stats(address)
    return profile


@app.post("/api/providers/{address}/follow")
async def follow_provider(address: str, request: Request):
    body = await request.json()
    user = normalize_address(body.get("user_address", ""))
    provider = normalize_address(address)
    if not user or not provider:
        raise HTTPException(status_code=400, detail="addresses required")
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO provider_follows (user_address, provider_address) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (user, provider))
    return {"status": "ok"}


# ─── Notifications ──────────────────────────────────────────

@app.post("/api/notifications/subscribe")
async def subscribe_notifications(request: Request):
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    subscription = body.get("subscription")
    if not address or not subscription:
        raise HTTPException(status_code=400, detail="address and subscription required")
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO push_subscriptions (user_address, subscription)
               VALUES (%s,%s) ON CONFLICT (user_address) DO UPDATE SET subscription=EXCLUDED.subscription""",
            (address, json.dumps(subscription)))
    return {"status": "ok"}


# ─── Share ───────────────────────────────────────────────────

@app.get("/api/share/{trade_id}/meta")
async def share_meta(trade_id: int):
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        raise HTTPException(status_code=404, detail="DB unavailable")
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM trades WHERE id = %s", (trade_id,))
        trade = cur.fetchone()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    pnl = trade.get("pnl_pct") or 0
    emoji = "🧠 CALLED IT" if pnl > 0 else "😭 REKT"
    return {
        "title": f"{emoji} | {trade['token_symbol']} {pnl:+.1f}%",
        "description": f"Entry ${trade['entry_price']:.2f} → Exit ${(trade.get('exit_price') or 0):.2f}",
        "image": f"/api/cards/{trade['card_id']}/image",
        "trade": dict(trade),
    }


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
