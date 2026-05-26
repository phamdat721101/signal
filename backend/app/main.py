import json
import logging
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.error_tracker import error_tracker
from app import db_async, http_client

# Configure logging once. Format includes request_id when present.
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


_LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
logging.basicConfig(level=get_settings().log_level, format=_LOG_FORMAT)
for h in logging.getLogger().handlers:
    h.addFilter(_RequestIdFilter())
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
    logger.info(f"Starting Initia Signal API | network={get_settings().network}")
    # Sync pool warm-up (legacy psycopg2)
    try:
        from app.db import _get_read_conn
        _get_read_conn()
    except Exception:
        pass
    # Reliability layer — chain_operations table for retry/idempotency on chain writes
    try:
        from app import chain_ops
        chain_ops.init_table()
    except Exception as e:
        logger.warning("chain_ops init failed (non-fatal): %s", e)
    # Swipe-session mirror tables
    try:
        from app import swipe_session
        swipe_session.init_table()
    except Exception as e:
        logger.warning("swipe_session init failed (non-fatal): %s", e)
    # Async pool for hot endpoints
    await db_async.init_pool()
    yield
    await db_async.close_pool()
    await http_client.close_async()
    http_client.close_sync()
    logger.info("Shutting down")


app = FastAPI(title="Initia Signal API", lifespan=lifespan)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach a request_id to logs; emit one access log line per request."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = _request_id_ctx.set(rid)
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.exception("request failed: %s %s after %dms", request.method, request.url.path, elapsed_ms)
        raise
    finally:
        _request_id_ctx.reset(token)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    response.headers["x-request-id"] = rid
    # Skip noisy access logs for /metrics-style polling; log at INFO otherwise.
    if request.url.path not in ("/api/health",):
        logger.info("%s %s -> %d (%dms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Agent API router
from app.agent_api import router as agent_v2_router
app.include_router(agent_v2_router)



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    code = "INTERNAL_ERROR"
    message = str(exc)
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": exc.detail}})
    error_tracker.track(code, message, context={
        "path": request.url.path,
        "method": request.method,
        "trace": traceback.format_exc()[-1000:],
    })
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
        "db_async": await db_async.health(),
        "circuits": error_tracker.summary().get("open_circuits", []),
        "chain_ops_pending_count": _safe_chain_ops_pending(),
    }


def _safe_chain_ops_pending() -> int:
    try:
        from app import chain_ops
        return chain_ops.pending_count()
    except Exception:
        return -1


def _require_admin(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    admin = get_settings().admin_token
    if not admin or token != admin:
        raise HTTPException(status_code=403, detail="Admin access required")


@app.get("/api/errors")
async def get_errors(request: Request, code: str | None = Query(default=None)):
    _require_admin(request)
    if code:
        return {"errors": error_tracker.get_by_code(code)}


@app.get("/api/crash-logs")
async def get_crash_logs(request: Request, lines: int = Query(default=50, le=200)):
    _require_admin(request)
    """Read persistent crash logs (survives restarts)."""
    from app.error_tracker import _LOG_DIR
    log_file = _LOG_DIR / "crash.log"
    if not log_file.exists():
        return {"logs": [], "summary": error_tracker.summary()}
    tail = log_file.read_text().strip().split("\n")[-lines:]
    return {"logs": tail, "summary": error_tracker.summary()}


_SKILL_MD = """# Signal Trading Intelligence API

## Capabilities
- Real-time AI-generated trading signals (APE/FADE/DYOR)
- Multi-agent debate analysis (Technical + Sentiment + Fundamentals)
- LP advisory with risk scoring
- Market context (ETF flows, macro events, sector rotation)
- Verifiable track record with on-chain proof

## Endpoints (x402 paid)
- GET /api/v2/agent/decisions — $0.001 — Actionable trade decisions
- GET /api/v2/agent/prices — $0.001 — Real-time aggregated prices
- GET /api/v2/agent/pools — $0.005 — LP opportunities
- GET /api/v2/agent/context — $0.01 — Full market context
- GET /api/v2/agent/track-record — FREE — Historical accuracy

## Payment
Protocol: x402 | Network: Base (eip155:8453) | Token: USDC
No API keys. No accounts. Just pay and access.

## Decision Schema
```json
{"action": "APE|FADE", "confidence": 1-100, "entry": 0.0, "target": 0.0, "stop": 0.0, "reasoning": "..."}
```

## Base URL
https://13-212-80-72.sslip.io/signal-api
"""


@app.get("/.well-known/SKILL.md")
@app.get("/SKILL.md")
async def skill_md():
    return PlainTextResponse(_SKILL_MD, media_type="text/markdown")
    return {"errors": error_tracker.get_recent(), "summary": error_tracker.summary()}





# ─── Card API (Ape or Fade) ──────────────────────────────────

@app.get("/api/cards")
async def get_cards_feed(offset: int = 0, limit: int = Query(default=20, le=50), card_type: str | None = Query(default=None)):
    cache_key = f"cards:{offset}:{limit}:{card_type or 'all'}"
    hit = cached(cache_key, ttl=60)
    if hit:
        return hit
    settings = get_settings()
    if not settings.database_url:
        return {"cards": [], "total": 0}
    from app.db import get_cards
    cards, total = get_cards(offset, limit, card_type=card_type)
    result = {"cards": cards, "total": total}
    set_cache(cache_key, result)
    return result


@app.get("/api/cards/played/{address}")
async def get_played_cards(address: str):
    """Return cards the user has APE'd (for CardHand display)."""
    address = normalize_address(address)
    if not address:
        return {"cards": []}
    from app.db import get_user_aped_cards
    cards = get_user_aped_cards(address)
    return {"cards": cards}


@app.get("/api/featured-gem")
async def get_featured_gem():
    """Single highest-scoring gem from last 24h. Splash hero on first open.

    Headers: max-age=60 keeps browser hot for 60s; SWR=900 lets the SW serve
    a stale gem for up to 15min while it revalidates in the background. Combined
    with our 60s in-process backend cache, the worst-case latency for a cold
    SW is one DB hit per minute globally.
    """
    cache_key = "featured-gem"
    headers = {"Cache-Control": "public, max-age=60, stale-while-revalidate=900"}
    hit = cached(cache_key, ttl=60)
    if hit:
        return JSONResponse(content=hit, headers=headers)
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="No database configured")
    from app.db import get_top_gem
    gem = get_top_gem()
    if not gem:
        raise HTTPException(status_code=503, detail="No gem available yet")
    set_cache(cache_key, gem)
    return JSONResponse(content=gem, headers=headers)


@app.get("/api/ticker")
async def get_ticker(addresses: str = Query(..., min_length=1)):
    """Bulk live prices keyed by token address. Used by the visible-card ticker.

    The 5s in-process cache coalesces concurrent requests into one upstream
    DEXScreener call every 5s globally, regardless of DAU.
    """
    addrs = [a.strip() for a in addresses.split(",") if a.strip()][:30]
    if not addrs:
        raise HTTPException(status_code=400, detail="No addresses supplied")
    cache_key = f"ticker:{','.join(sorted(a.lower() for a in addrs))}"
    headers = {"Cache-Control": "public, max-age=5"}
    hit = cached(cache_key, ttl=5)
    if hit is not None:
        return JSONResponse(content=hit, headers=headers)
    from app.price_feed import get_bulk_by_address
    data = get_bulk_by_address(addrs)
    set_cache(cache_key, data)
    return JSONResponse(content=data, headers=headers)


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
        return False  # fail-closed: require confirmed session for premium


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
    # Energy gate (no-op when disabled — see Settings.energy_gating_enabled)
    if address and get_settings().energy_gating_enabled:
        from app.db import consume_energy
        result = consume_energy(address, card.get("card_type", "trading"))
        if not result["ok"]:
            raise HTTPException(status_code=402, detail="no_energy")
    price = card.get("price", 0)
    # Non-price cards (macro_desk, whale_alert) — record swipe only, no trade
    if price <= 0:
        record_swipe(card_id, address, "ape")
        return {"status": "ok", "action": "ape", "trade": None, "conviction": None}
    token_amount = amount_usd / price
    on_chain = bool(tx_hash)
    if not tx_hash:
        import os
        tx_hash = f"sim_{os.urandom(16).hex()}"
        execution_type = "simulated"
    else:
        execution_type = "confirmed"
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


@app.post("/api/cards/{card_id}/play")
async def get_play_calldata(card_id: int, request: Request):
    """X Layer summon bundle — approve OKB + approve USDC + playCard.

    SOLID single responsibility: the backend assembles the multi-call bundle
    so the frontend never computes ticks or selectors. The hook contract
    enforces the recipe at beforeAddLiquidity; we just ship the calls.
    """
    from app.config import get_settings
    from app.db import get_card_by_id
    from app import xlayer

    s = get_settings()
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    if not address:
        raise HTTPException(status_code=400, detail="address required")

    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Hook deploy must be configured before this endpoint is usable.
    missing = [k for k, v in {
        "router": s.signal_card_router_address,
        "okb": s.okb_address_xlayer,
        "usdc": s.usdc_address_xlayer,
    }.items() if not v]
    if missing:
        raise HTTPException(status_code=503, detail=f"X Layer not configured: missing {missing}")

    entry = float(card.get("price") or 0)
    card_type = (card.get("card_type") or "").lower()
    # Single eligibility gate. Mirrors frontend isCardTradeable() so the user
    # gets a clean message even if FE gating is bypassed. Cards without a
    # tradeable price OR with an informational-only card_type cannot be
    # turned into LP recipes — the v4 hook would revert anyway.
    NON_TRADEABLE = {"macro_desk", "whale_alert", "index_battle", "insight", "pool"}
    if entry <= 0 or card_type in NON_TRADEABLE:
        sym = card.get("token_symbol") or f"#{card_id}"
        raise HTTPException(
            status_code=422,
            detail=f"Card ${sym} is not tradeable on X Layer (no LP recipe — informational card).",
        )
    # Synthetic ±1.5% range when target/stop missing — keeps existing trading cards usable.
    target = float(card.get("target_price") or entry * 1.015)
    stop = float(card.get("stop_price") or entry * 0.985)
    is_bull = (card.get("verdict") or "APE").upper() == "APE"

    # OKB price — lazy fetch via existing price_feed; default to $50 if unavailable.
    okb_usd_price = 50.0
    try:
        from app.price_feed import get_price
        p = get_price("OKB")
        if p and p > 0:
            okb_usd_price = p
    except Exception:
        pass

    # Compute ticks for the card
    lower, upper = xlayer.compute_card_ticks(entry, target, stop, is_bull)

    # Mint a fresh NFT on-chain for this user + card (uses deployer key as minter)
    nft_card_id = card_id + 100000  # offset to avoid collision with demo cards 1-5
    try:
        xlayer.mint_card_onchain(
            nft_address=s.signal_card_nft_address,
            card_id=nft_card_id,
            recipient=address,
            token_symbol=card.get("token_symbol", "?")[:8],
            tick_lower=lower,
            tick_upper=upper,
            risk_score=min(100, int(card.get("risk_score") or 50)),
            rarity=["common", "rare", "epic", "legendary", "mythic"].index(
                (card.get("rarity") or "common").lower()
            ) if (card.get("rarity") or "common").lower() in ["common", "rare", "epic", "legendary", "mythic"] else 0,
            is_bull=is_bull,
            rpc_url=s.xlayer_testnet_json_rpc_url,
            private_key=s.private_key,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NFT mint failed: {e}")

    bundle = xlayer.build_play_bundle(
        card_id=nft_card_id,
        chain_id=1952,
        entry=entry,
        target=target,
        stop=stop,
        is_bull=is_bull,
        router=s.signal_card_router_address,
        okb=s.okb_address_xlayer,
        usdc=s.usdc_address_xlayer,
        okb_usd_price=okb_usd_price,
    )

    return {
        "cardId": bundle.card_id,
        "chainId": bundle.chain_id,
        "tickLower": bundle.tick_lower,
        "tickUpper": bundle.tick_upper,
        "router": bundle.router,
        "okb": bundle.okb,
        "usdc": bundle.usdc,
        "amount0Max": str(bundle.amount0_max),
        "amount1Max": str(bundle.amount1_max),
        "liquidity": str(bundle.liquidity),
        "calls": bundle.calls,
        "deadline": bundle.deadline,
    }


@app.post("/api/lp/record")
async def record_lp_transaction(request: Request):
    """Store LP interaction (summon/close) for portfolio tracking."""
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    if not address:
        raise HTTPException(status_code=400, detail="address required")
    from app.db import record_lp_tx
    record_lp_tx(
        user_address=address,
        card_id=body.get("card_id"),
        tx_hash=body.get("tx_hash", ""),
        action=body.get("action", "summon"),  # summon | close
        chain_id=body.get("chain_id", 1952),
    )
    return {"status": "ok"}


@app.get("/api/lp/history/{address}")
async def get_lp_history(address: str):
    """Get LP transaction history for portfolio."""
    address = normalize_address(address)
    if not address:
        return {"transactions": []}
    from app.db import get_lp_history
    return {"transactions": get_lp_history(address)}


@app.post("/api/cards/{card_id}/close")
async def get_close_calldata(card_id: int, request: Request):
    """X Layer close bundle — remove LP for a played card."""
    from app.config import get_settings
    from app.db import get_card_by_id
    from app import xlayer

    s = get_settings()
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    if not address:
        raise HTTPException(status_code=400, detail="address required")

    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if not s.signal_card_router_address:
        raise HTTPException(status_code=503, detail="X Layer not configured")

    close_bundle = xlayer.build_close_bundle(
        card_id=((card_id - 1) % 5) + 1,  # Map DB card ID → on-chain NFT ID (1-5 demo cards)
        chain_id=1952,
        router=s.signal_card_router_address,
    )

    return {
        "cardId": close_bundle.card_id,
        "chainId": close_bundle.chain_id,
        "calls": close_bundle.calls,
        "deadline": close_bundle.deadline,
    }


@app.post("/api/cards/{card_id}/fade")
async def fade_card(card_id: int, request: Request):
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    from app.db import record_swipe, get_card_by_id
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    # Energy gate (no-op when disabled — see Settings.energy_gating_enabled)
    if address and get_settings().energy_gating_enabled:
        from app.db import consume_energy
        result = consume_energy(address, card.get("card_type", "trading"))
        if not result["ok"]:
            raise HTTPException(status_code=402, detail="no_energy")
    swipe_id = record_swipe(card_id, address, "fade")
    return {"status": "ok", "swipe_id": swipe_id, "action": "fade"}


@app.get("/api/energy/{address}")
async def get_user_energy(address: str):
    """Energy state for the energy bar UI.

    Premium path (active SessionVault session): unlimited energy, is_premium=true.
    Falls back to daily_swipes-derived count on RPC error or when no session.
    """
    import asyncio as _aio
    from app.config import get_settings
    from app.db import get_energy
    s = get_settings()
    address = normalize_address(address)
    # Gating disabled → unlimited for everyone (anonymous + connected).
    if not s.energy_gating_enabled:
        return {"energy": 999, "max": 999, "is_premium": True}
    if not address:
        return {"energy": s.energy_max, "max": s.energy_max, "is_premium": False}

    # Chain-derived premium check (60s cached). Wrapped in to_thread because
    # web3.py is sync; never block the event loop in an async handler.
    is_premium = False
    try:
        from app.chain import ChainClient
        is_premium = await _aio.to_thread(ChainClient().has_active_session, address)
    except Exception:
        is_premium = False  # fail-open to daily_swipes path

    if is_premium:
        return {"energy": s.energy_max, "max": s.energy_max, "is_premium": True}
    return {"energy": get_energy(address), "max": s.energy_max, "is_premium": False}


@app.post("/api/energy/refill")
async def refill_energy(request: Request):
    """Reset daily_swipes after a verified SessionVault deposit.

    Requires {address, tx_hash}. Verifies the tx receipt's SessionCreated event
    proves `address` is the depositor. Idempotent on tx_hash — replaying
    returns the same response without doing on-chain work twice.
    """
    import asyncio as _aio
    from app.config import get_settings
    from app import db
    s = get_settings()
    body = await request.json()
    address = normalize_address(body.get("address", ""))
    tx_hash = (body.get("tx_hash") or "").strip().lower()

    if not address:
        raise HTTPException(400, "address required")
    if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
        raise HTTPException(400, "tx_hash required (0x + 64 hex chars)")

    # Idempotent replay — same tx_hash returns the same outcome with no chain RPC.
    if await _aio.to_thread(db.get_refill, tx_hash):
        return {"energy": s.energy_max, "max": s.energy_max,
                "tx_hash": tx_hash, "redeemed": True, "replayed": True}

    # Verify the deposit happened on-chain and matches the caller.
    from app.chain import ChainClient
    result = await _aio.to_thread(
        ChainClient().verify_session_creation_tx, tx_hash, address)
    if not result.get("ok"):
        raise HTTPException(403, f"tx does not prove deposit: {result.get('reason')}")

    # Persist refill (idempotency boundary) + clear today's swipe count.
    await _aio.to_thread(
        db.record_refill, tx_hash, address,
        result.get("session_id"), result.get("amount"))
    await _aio.to_thread(db.reset_daily_swipes, address)

    return {"energy": s.energy_max, "max": s.energy_max,
            "tx_hash": tx_hash, "redeemed": True, "replayed": False,
            "session_id": result.get("session_id"),
            "expires_at": result.get("expires_at")}


@app.get("/api/cards/user/{address}")
async def get_user_card_history(address: str, offset: int = 0, limit: int = Query(default=50, le=100)):
    address = normalize_address(address)
    from app.db import get_user_swipes
    swipes, total = get_user_swipes(address, offset, limit)
    return {"swipes": swipes, "total": total}




# ─── Hook the Future: Card-Summon LP endpoints (X Layer testnet) ────────
@app.post("/api/cards/{card_id}/play")
async def get_card_play_data(card_id: int, request: Request):
    """Return pre-computed tick range + Router calldata for a card-summon LP open.

    Frontend calls this, then signs the Router.playCard tx with the returned data.
    """
    from app.db import get_card_by_id
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    from app.config import get_settings
    s = get_settings()
    # Pre-compute ticks from card's entry/target/stop prices
    # For hackathon: ticks are stored directly in the card (backend mints with pre-computed ticks)
    import math
    entry = card.get("price", 1.0)
    target = entry * 1.015 if card.get("verdict") == "APE" else entry * 0.985
    stop = entry * 0.985 if card.get("verdict") == "APE" else entry * 1.015
    tick_spacing = 60
    def price_to_tick(p): return int(math.log(max(p, 1e-18)) / math.log(1.0001))
    def round_tick(t, spacing, up=False):
        if up: return ((t + spacing - 1) // spacing) * spacing
        return (t // spacing) * spacing
    raw_lower = price_to_tick(stop)
    raw_upper = price_to_tick(target)
    tick_lower = round_tick(min(raw_lower, raw_upper), tick_spacing)
    tick_upper = round_tick(max(raw_lower, raw_upper), tick_spacing, up=True)
    if tick_lower == tick_upper:
        tick_upper += tick_spacing
    return {
        "cardId": card_id,
        "tickLower": tick_lower,
        "tickUpper": tick_upper,
        "riskScore": card.get("risk_score", 50),
        "verdict": card.get("verdict", "APE"),
        "rarity": card.get("rarity", "common"),
        "routerAddress": os.environ.get("SIGNAL_CARD_ROUTER_ADDRESS", ""),
        "nftAddress": os.environ.get("SIGNAL_CARD_NFT_ADDRESS", ""),
        "chainId": 1952,
    }


@app.post("/api/cards/{card_id}/buy")
async def buy_card_agent(card_id: int, request: Request):
    """Agent buy path — returns 402 Payment Required with x402-compatible challenge.

    Agent pays MockUSDC on X Layer testnet; backend mints the card NFT to agent's address.
    """
    from app.db import get_card_by_id
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    # Check if agent already paid (x-payment header present)
    x_payment = request.headers.get("x-payment")
    if not x_payment:
        # Return 402 challenge
        return JSONResponse(status_code=402, content={
            "x402Version": 2,
            "accepts": [{
                "scheme": "exact",
                "network": "eip155:1952",
                "asset": os.environ.get("XLAYER_MOCK_USDC", ""),
                "amount": "1000000",  # 1 USDC (6 decimals)
                "payTo": os.environ.get("X402_RECEIVER_ADDRESS", ""),
            }],
            "resource": {"url": f"/api/cards/{card_id}/buy", "type": "http"},
        })
    # If x-payment present, treat as paid (hackathon simplification — no real verification on testnet)
    body = await request.json()
    agent_address = body.get("address", "")
    return {
        "status": "paid",
        "cardId": card_id,
        "mintTo": agent_address,
        "message": "Card NFT will be minted to your address. Call Router.playCard to open LP.",
    }


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
        "loss_count": sum(1 for t in resolved if (t.get("pnl_usd") or 0) <= 0),
        "resolved_count": len(resolved),
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
    # Trading IQ — engagement + conviction-aware (DB-derived, never stuck at 0)
    # RewardEngine fields lag because onTradeResolved only fires after a 24h
    # resolution; meanwhile the user's swipes/convictions are real activity.
    db_total       = trades_data["summary"].get("total_trades", 0)
    db_wins        = trades_data["summary"].get("win_count", 0)
    db_losses      = trades_data["summary"].get("loss_count", 0)
    conv_total     = conviction_data.get("totalConvictions", 0)
    conv_correct   = conviction_data.get("correctCalls", 0)
    best_streak    = max(streak, conviction_data.get("bestStreak", 0))
    iq = max(
        0,
        db_total       * 2          # engagement: every swipe earns IQ
      + conv_total     * 3          # on-chain proof of activity (verifiable)
      + db_wins        * 10         # resolved wins
      + conv_correct   * 8          # oracle-verified correct calls
      - db_losses      * 3          # penalize ONLY resolved losses, never pending
      + best_streak    * 5
      + earned         * 25
      + on_chain_rep   // 10
    )
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


_faucet_limits: dict[str, float] = {}
FAUCET_COOLDOWN = 300  # 5 minutes


def _check_faucet_rate(address: str):
    now = time.time()
    last = _faucet_limits.get(address, 0)
    if now - last < FAUCET_COOLDOWN:
        raise HTTPException(status_code=429, detail=f"Rate limited. Try again in {int(FAUCET_COOLDOWN - (now - last))}s")
    _faucet_limits[address] = now


@app.post("/api/payment/faucet")
async def claim_faucet(address: str):
    address = normalize_address(address)
    if not address:
        raise HTTPException(status_code=400, detail="Invalid address")
    if get_settings().network == "mainnet":
        raise HTTPException(status_code=403, detail="Faucet disabled on mainnet")
    _check_faucet_rate(address)
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
        if not receipt or receipt.get("status") != 1:
            raise HTTPException(status_code=500, detail="Mint transaction reverted on-chain")
        return {"status": "ok", "amount": "1000", "token": "iUSD", "recipient": address, "txHash": "0x" + receipt["transactionHash"].hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/faucet/gas")
async def gas_faucet(address: str):
    """Removed 2026-05-18 — users fund their wallet via the Initia L1 bridge.

    Kept as a 410 Gone for any clients still pointing at this URL so they get
    an explicit signal instead of a misleading 404.
    """
    raise HTTPException(
        status_code=410,
        detail="Gas faucet removed. Bridge from Initia L1: https://bridge.initia.xyz/?to=initia-signal-1",
    )





# ─── Agent-Optimized Endpoints ────────────────────────────────
@app.get("/api/agent/signals/active")
async def agent_signals_active(limit: int = Query(default=10, le=50)):
    """Machine-optimized active trading signals for AI agents."""
    from app.db import get_cards
    cards, _ = get_cards(0, limit)
    signals = []
    for c in cards:
        if c.get("verdict") not in ("APE", "FADE"):
            continue
        entry = c.get("price", 0)
        if entry <= 0:
            continue
        is_bull = c["verdict"] == "APE"
        signals.append({
            "id": c["id"], "token": c["token_symbol"], "action": c["verdict"],
            "confidence": max(10, 100 - (c.get("risk_score") or 50)),
            "entry": round(entry, 6),
            "target": round(entry * (1.015 if is_bull else 0.985), 6),
            "stop": round(entry * (0.985 if is_bull else 1.015), 6),
            "risk_score": c.get("risk_score", 50),
            "reasoning": c.get("verdict_reason", ""),
            "signals": c.get("signals", [])[:3],
            "created_at": c.get("created_at", ""),
            "source": c.get("source", "ai"),
        })
    return {"signals": signals, "total": len(signals), "format": "agent-v1"}


@app.get("/api/agent/accuracy")
async def agent_accuracy():
    """Historical accuracy stats for agent decision-making."""
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        return {"overall": {"total_trades": 0, "wins": 0, "win_rate": 0}, "per_token": {}}
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) as total, SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins FROM trades WHERE resolved = true")
        overall = cur.fetchone()
        cur.execute("""
            SELECT token_symbol, COUNT(*) as total,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                ROUND(AVG(pnl_pct)::numeric, 2) as avg_pnl_pct
            FROM trades WHERE resolved = true
            GROUP BY token_symbol HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC LIMIT 20
        """)
        rows = cur.fetchall()
    per_token = {}
    for r in rows:
        per_token[r["token_symbol"]] = {
            "total_trades": r["total"], "wins": r["wins"],
            "win_rate": round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0,
            "avg_pnl_pct": float(r["avg_pnl_pct"] or 0),
        }
    return {
        "overall": {
            "total_trades": overall["total"] or 0, "wins": overall["wins"] or 0,
            "win_rate": round((overall["wins"] or 0) / max(overall["total"] or 1, 1) * 100, 1),
        },
        "per_token": per_token,
    }


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




# ─── SKILL.md (Agent Discovery) ─────────────────────────────

@app.get("/SKILL.md")
@app.get("/.well-known/SKILL.md")
async def skill_md():
    return PlainTextResponse("""# Initia Signal — Ape or Fade

AI-powered on-chain trading signal service on Initia EVM appchain.

## Agent-Optimized Endpoints (Free — no payment needed)

### `GET /api/agent/signals/active`
Structured trading signals for AI agent consumption. Returns entry/target/stop prices, confidence, reasoning.
Query: ?limit=10 (max 50)
Returns: {signals: [{id, token, action, confidence, entry, target, stop, reasoning, risk_score, source}], total, format}

### `GET /api/agent/accuracy`
Historical accuracy statistics per token and overall win rate.
Returns: {overall: {total_trades, wins, win_rate}, per_token: {SYMBOL: {total_trades, wins, win_rate, avg_pnl_pct}}}

## Payment

Premium endpoints require an active SessionVault session or x402 payment.
See GET /api/payment/pricing for details.
""")



# ─── Swipe-session mirror (frontend useSwipeSession recovery surface) ──

@app.post("/api/swipe-session/start")
async def swipe_session_start(payload: dict):
    """Mirror the start of a swipe session. Frontend localStorage is truth.

    Body: {"user": "0x...", "tx_hash": "0x...", "duration_hours": 24, "session_id"?: "..."}
    """
    from app import swipe_session
    user = (payload.get("user") or "").strip()
    if not user:
        raise HTTPException(status_code=400, detail="user required")
    # session_id may be 'pending' until we read it from the createSession event;
    # frontend can patch it later by re-calling start with the resolved id.
    session_id = str(payload.get("session_id") or "pending")
    swipe_session.start(
        session_id, user,
        start_tx_hash=payload.get("tx_hash"),
        duration_hours=int(payload.get("duration_hours") or 24),
    )
    return {"ok": True, "session_id": session_id}


@app.post("/api/swipe-session/{session_id}/queue")
async def swipe_session_queue(session_id: str, payload: dict):
    """Mirror one queued swipe. Idempotent on (session_id, card_id)."""
    from app import swipe_session
    swipe_session.queue(session_id, payload)
    return {"ok": True}


@app.post("/api/swipe-session/{session_id}/settle")
async def swipe_session_settle(session_id: str, payload: dict):
    """Mark session settled. Idempotent."""
    from app import swipe_session
    tx_hash = (payload.get("tx_hash") or "").strip()
    if not tx_hash:
        raise HTTPException(status_code=400, detail="tx_hash required")
    swipe_session.settle(session_id, tx_hash)
    return {"ok": True}


@app.get("/api/swipe-session/{session_id}")
async def swipe_session_get(session_id: str):
    """Recovery: read the full session + queue."""
    from app import swipe_session
    s = swipe_session.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    return s
