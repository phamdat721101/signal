"""Agent API v2 — structured endpoints for AI agent consumption."""
import logging
import time
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app import db, db_async
from app.db import _get_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agent", tags=["agent"])

ALLOWED_AGENT_FIELDS = {"strategy", "max_position_usd", "tokens_whitelist", "tokens_blacklist",
                         "min_confidence", "auto_execute", "risk_tolerance", "take_profit_pct",
                         "stop_loss_pct", "is_active"}

# Tiny in-process TTL cache for read-mostly endpoints. Per-worker; that's fine
# at the current scale. Promote to a shared cache module when a 3rd file needs it.
_cache: dict[str, tuple[float, object]] = {}


def _cache_get(key: str, ttl: int) -> object | None:
    entry = _cache.get(key)
    return entry[1] if entry and time.time() - entry[0] < ttl else None


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (time.time(), value)


def _verify_ownership(body_address: str, header_address: str | None):
    """Verify caller owns the address via X-Wallet-Address header."""
    if not header_address or body_address.lower() != header_address.lower():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="X-Wallet-Address header must match request address")


async def _batch_track_record(symbols: list[str]) -> dict[str, dict]:
    """One query for all symbols. Replaces the N+1 _get_token_track_record loop."""
    if not symbols or not db_async.is_ready():
        return {}
    rows = await db_async.fetch_all(
        """
        SELECT token_symbol,
               COUNT(*) AS total,
               SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) AS wins
        FROM agent_predictions
        WHERE token_symbol = ANY($1::text[]) AND resolved_at IS NOT NULL
        GROUP BY token_symbol
        """,
        symbols,
    )
    return {
        r["token_symbol"]: {
            "win_rate": round((r["wins"] or 0) / r["total"] * 100, 1) if r["total"] else 0,
            "sample_size": r["total"] or 0,
        }
        for r in rows
    }


@router.get("/decisions")
async def get_decisions(limit: int = Query(default=10, le=50)):
    """Structured trading decisions for AI agents. Cached 20s."""
    cache_key = f"decisions:{limit}"
    hit = _cache_get(cache_key, ttl=20)
    if hit is not None:
        return hit

    if not db_async.is_ready():
        # Fallback to legacy sync path if async pool isn't up
        cards, _ = db.get_cards(0, limit)
        rows = cards
    else:
        # SELECT * keeps us schema-tolerant — older DBs may lack rarity/etc.
        rows = await db_async.fetch_all(
            """
            SELECT *
            FROM cards
            WHERE status = 'active' AND price > 0
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )

    symbols = [r["token_symbol"] for r in rows if r.get("token_symbol")]
    track_records = await _batch_track_record(symbols)

    decisions = []
    for c in rows:
        entry = c.get("price") or 0
        if entry <= 0:
            continue
        is_bull = c.get("verdict") == "APE"
        decisions.append({
            "id": c["id"],
            "type": "liquidity" if c.get("card_type") == "pool" else "trading",
            "token": c["token_symbol"],
            "action": c.get("verdict") or "HOLD",
            "confidence": max(10, 100 - (c.get("risk_score") or 50)),
            "entry": round(entry, 6),
            "target": round(entry * (1.015 if is_bull else 0.985), 6),
            "stop": round(entry * (0.985 if is_bull else 1.015), 6),
            "reasoning": c.get("verdict_reason") or "",
            "rarity": c.get("rarity") or "common",
            "track_record": track_records.get(c["token_symbol"], {"win_rate": 0, "sample_size": 0}),
        })
    result = {"decisions": decisions, "total": len(decisions)}
    _cache_set(cache_key, result)
    return result


@router.get("/prices")
async def get_prices(symbols: str = Query(..., description="Comma-separated symbols")):
    """Aggregated prices from best available source. Offloaded to threadpool."""
    import asyncio
    from app.price_feed import get_prices as fetch_prices
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    prices = await asyncio.to_thread(fetch_prices, symbol_list)
    return {"prices": prices}


@router.get("/pools")
async def get_pools(limit: int = Query(default=10, le=50)):
    """LP advisory opportunities. Cached 60s."""
    cache_key = f"pools:{limit}"
    hit = _cache_get(cache_key, ttl=60)
    if hit is not None:
        return hit

    if not db_async.is_ready():
        cards, total = db.get_cards(0, limit, card_type="pool")
    else:
        cards = await db_async.fetch_all(
            """
            SELECT * FROM cards
            WHERE card_type = 'pool' AND status = 'active'
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        total = len(cards)
    result = {"pools": cards, "total": total}
    _cache_set(cache_key, result)
    return result


@router.get("/track-record")
async def get_track_record():
    """Historical accuracy stats. Cached 60s."""
    cache_key = "track_record:overall"
    hit = _cache_get(cache_key, ttl=60)
    if hit is not None:
        return hit

    if not db_async.is_ready():
        return {"overall": {"total": 0, "wins": 0, "win_rate": 0}, "per_token": {}}

    overall = await db_async.fetch_one(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) AS wins "
        "FROM agent_predictions WHERE resolved_at IS NOT NULL"
    ) or {"total": 0, "wins": 0}
    rows = await db_async.fetch_all(
        """
        SELECT token_symbol,
               COUNT(*) AS total,
               SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) AS wins,
               ROUND(AVG(outcome_pct)::numeric, 2) AS avg_pnl
        FROM agent_predictions
        WHERE resolved_at IS NOT NULL
        GROUP BY token_symbol HAVING COUNT(*) >= 3
        ORDER BY COUNT(*) DESC LIMIT 20
        """
    )
    total = overall["total"] or 0
    wins = overall["wins"] or 0
    per_token = {
        r["token_symbol"]: {
            "total": r["total"],
            "wins": r["wins"] or 0,
            "win_rate": round((r["wins"] or 0) / r["total"] * 100, 1),
            "avg_pnl": float(r["avg_pnl"] or 0),
        }
        for r in rows
    }
    result = {
        "overall": {"total": total, "wins": wins, "win_rate": round(wins / max(total, 1) * 100, 1)},
        "per_token": per_token,
    }
    _cache_set(cache_key, result)
    return result


@router.get("/context")
async def get_context():
    """Market context: SoSoValue data + oracle mood. Cached 30s, offloaded to threadpool."""
    import asyncio
    from app.sosovalue_client import get_full_context
    from app.degen_oracle import get_current_mood

    hit = _cache_get("context", ttl=30)
    if hit is not None:
        return hit
    sosovalue, mood = await asyncio.gather(
        asyncio.to_thread(get_full_context),
        asyncio.to_thread(get_current_mood),
    )
    result = {"sosovalue": sosovalue, "oracle_mood": mood}
    _cache_set("context", result)
    return result


# ─── User Agent Config Endpoints ─────────────────────────────

@router.get("/my-agent")
async def get_my_agent(address: str = Query(...)):
    """Get user's agent config + learned preferences + wallet."""
    agent = db.get_user_agent(address)
    if not agent:
        return {"agent": None, "learned": db.compute_preferences_from_swipes(address)}
    # Attach stellar wallet if exists
    conn = db._get_conn()
    if conn:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT stellar_public_key FROM agent_wallets WHERE user_address=%s", (address,))
            row = cur.fetchone()
            if row:
                agent["stellar_public_key"] = row["stellar_public_key"]
    return {"agent": agent, "learned": agent.get("learned_preferences") or db.compute_preferences_from_swipes(address)}


@router.put("/my-agent")
async def upsert_my_agent(request: Request):
    """Create or update user's agent config. Generates OWS wallet on first create."""
    body = await request.json()
    address = body.get("address", "")
    if not address:
        return {"error": "address required"}
    _verify_ownership(address, request.headers.get("x-wallet-address"))
    config = {k: v for k, v in body.items() if k in ALLOWED_AGENT_FIELDS}

    # Check if agent already exists
    existing = db.get_user_agent(address)
    agent = db.upsert_user_agent(address, config)

    # Generate OWS wallet on first creation
    if not existing and agent:
        from app.trustless_escrow import generate_agent_wallet
        wallet = generate_agent_wallet()
        _store_agent_wallet(address, wallet["public_key"], wallet["secret"])
        agent["stellar_public_key"] = wallet["public_key"]

    # Auto-compute learned preferences on first create
    if agent and not agent.get("learned_preferences"):
        prefs = db.compute_preferences_from_swipes(address)
        if prefs:
            conn = db._get_conn()
            if conn:
                import json as _json
                with conn.cursor() as cur:
                    cur.execute("UPDATE user_agents SET learned_preferences=%s WHERE user_address=%s",
                                (_json.dumps(prefs), address))
                agent["learned_preferences"] = prefs
    return {"agent": agent}


def _store_agent_wallet(user_address: str, public_key: str, secret: str):
    """Store agent's Stellar wallet in DB."""
    conn = db._get_conn()
    if not conn:
        return
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO agent_wallets (user_address, stellar_public_key, encrypted_secret)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_address) DO NOTHING
        """, (user_address, public_key, secret))
        cur.execute("UPDATE user_agents SET stellar_public_key=%s WHERE user_address=%s",
                    (public_key, user_address))


def _get_agent_wallet_secret(user_address: str) -> str | None:
    """Retrieve agent wallet secret for signing."""
    conn = db._get_conn()
    if not conn:
        return None
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT encrypted_secret FROM agent_wallets WHERE user_address=%s", (user_address,))
        row = cur.fetchone()
    return row["encrypted_secret"] if row else None


@router.post("/my-agent/toggle")
async def toggle_agent(request: Request):
    """Activate or deactivate user's agent."""
    body = await request.json()
    address = body.get("address", "")
    if not address:
        return {"error": "address required"}
    _verify_ownership(address, request.headers.get("x-wallet-address"))
    agent = db.get_user_agent(address)
    if not agent:
        return {"error": "no agent configured"}
    new_state = not agent["is_active"]
    db.upsert_user_agent(address, {"is_active": new_state})
    return {"is_active": new_state}


@router.get("/my-agent/notifications")
async def get_notifications(address: str = Query(...), limit: int = Query(default=20, le=50)):
    """Get agent notifications for user."""
    return {"notifications": db.get_agent_notifications(address, limit)}


@router.get("/my-agent/stats")
async def get_agent_stats(address: str = Query(...)):
    """Get agent trading stats."""
    conn = db._get_conn()
    if not conn:
        return {"total": 0, "wins": 0, "pnl_usd": 0}
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                   COALESCE(SUM(pnl_usd), 0) as pnl_usd
            FROM trades WHERE user_address=%s AND source='agent'
        """, (address,))
        row = cur.fetchone()
    total = row["total"] or 0
    wins = row["wins"] or 0
    return {"total": total, "wins": wins, "win_rate": round(wins / max(total, 1) * 100, 1), "pnl_usd": round(float(row["pnl_usd"] or 0), 2)}


# ─── Marketplace Endpoints (Trustless Work Escrow) ────────────

@router.post("/marketplace/subscribe")
async def subscribe_signal(request: Request):
    """Subscribe to a signal — returns unsigned deploy XDR for user to sign."""
    body = await request.json()
    subscriber_stellar = body.get("subscriber_stellar", "")
    signal_id = body.get("signal_id")
    amount = body.get("amount_usdc", 5.0)
    if not subscriber_stellar or not signal_id:
        return {"error": "subscriber_stellar and signal_id required"}

    card = db.get_card_by_id(signal_id)
    if not card:
        cards, _ = db.get_cards(0, 1)
        card = cards[0] if cards else None
    if not card:
        return {"error": "no signals available"}

    from app.trustless_escrow import deploy_escrow
    from app.config import get_settings as _gs
    platform_addr = _gs().stellar_platform_address
    if not platform_addr:
        return {"error": "Stellar platform not configured"}

    try:
        deploy_result = await deploy_escrow(subscriber_stellar, platform_addr, amount, card["id"])
    except Exception as e:
        return {"error": f"Escrow deploy failed: {e}"}

    # Deploy returns unsigned XDR — user must sign and submit via /helper/send-transaction
    unsigned_xdr = deploy_result.get("unsignedTransaction", "")

    # Store pending escrow
    conn = db._get_conn()
    if conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO signal_escrows (signal_id, subscriber_stellar, provider_stellar, escrow_contract, amount_usdc, status) VALUES (%s,%s,%s,%s,%s,'pending')",
                (card["id"], subscriber_stellar, platform_addr, "", amount))
        db._put_conn(conn)

    return {
        "unsigned_xdr": unsigned_xdr,
        "amount_usdc": amount,
        "signal_id": card["id"],
        "token_symbol": card.get("token_symbol", ""),
        "verdict": card.get("verdict", ""),
    }


@router.post("/marketplace/submit-tx")
async def submit_signed_tx(request: Request):
    """Submit a signed XDR to Stellar via Trustless Work helper."""
    body = await request.json()
    signed_xdr = body.get("signed_xdr", "")
    if not signed_xdr:
        return {"error": "signed_xdr required"}
    try:
        from app.trustless_escrow import submit_transaction
        result = await submit_transaction(signed_xdr)
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"error": f"Submit failed: {e}"}


@router.get("/marketplace/escrows")
async def get_user_escrows(address: str = Query(...)):
    """Get user's active escrows."""
    conn = db._get_conn()
    if not conn:
        return {"escrows": []}
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT e.*, c.token_symbol, c.verdict, c.price, c.hook
            FROM signal_escrows e
            LEFT JOIN cards c ON c.id = e.signal_id
            WHERE e.subscriber_stellar = %s
            ORDER BY e.created_at DESC LIMIT 20
        """, (address,))
        rows = cur.fetchall()
    return {"escrows": [dict(r) for r in rows]}


@router.get("/marketplace/providers")
async def get_providers():
    """Get signal providers with track records."""
    conn = db._get_conn()
    if not conn:
        return {"providers": []}
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 'AI Signal Engine' as name, COUNT(*) as total_signals,
                   SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as wins,
                   ROUND(AVG(outcome_pct)::numeric, 2) as avg_pnl
            FROM agent_predictions WHERE resolved_at IS NOT NULL
        """)
        row = cur.fetchone()
    total = row["total_signals"] or 0
    wins = row["wins"] or 0
    return {"providers": [{
        "name": "AI Signal Engine",
        "win_rate": round(wins / max(total, 1) * 100, 1),
        "total_signals": total,
        "avg_pnl": float(row["avg_pnl"] or 0),
        "price_usdc": 5.0,
    }]}


# ─── Premium Report Escrow ────────────────────────────────────

REPORT_TYPES = {
    "market_overview": {"price_usdc": 2.0, "description": "Full market analysis with top 5 signals, ETF flows, sentiment"},
    "token_deep_dive": {"price_usdc": 5.0, "description": "Deep analysis on a specific token with multi-agent debate"},
    "portfolio_advisory": {"price_usdc": 10.0, "description": "Personalized portfolio allocation + risk assessment"},
}


@router.get("/reports")
async def list_report_types():
    """Available premium report types and pricing."""
    return {"reports": REPORT_TYPES}


@router.post("/reports/purchase")
async def purchase_report(request: Request):
    """Deploy escrow (platform signs server-side) and return fund XDR for user to sign."""
    body = await request.json()
    report_type = body.get("report_type", "market_overview")
    buyer_stellar = body.get("buyer_stellar", "")
    if report_type not in REPORT_TYPES:
        raise HTTPException(400, "Invalid report_type")
    if not buyer_stellar:
        raise HTTPException(400, "buyer_stellar required")

    from app.config import get_settings as _gs
    s = _gs()
    if not s.stellar_platform_address or not s.stellar_platform_secret:
        raise HTTPException(503, "Stellar platform not configured")

    import uuid
    engagement_id = f"report-{uuid.uuid4().hex[:12]}"
    amount = REPORT_TYPES[report_type]["price_usdc"]

    # Step 1: Deploy escrow (returns unsigned XDR for platform to sign)
    from app.trustless_escrow import deploy_escrow, submit_transaction
    try:
        deploy_result = await deploy_escrow(buyer_stellar, s.stellar_platform_address, amount, 0)
    except Exception as e:
        raise HTTPException(503, f"Escrow deploy failed: {e}")

    unsigned_xdr = deploy_result.get("unsignedTransaction", "")
    if not unsigned_xdr:
        raise HTTPException(503, "No transaction returned from escrow deploy")

    # Step 2: Platform signs the deploy XDR server-side
    from stellar_sdk import Keypair, TransactionEnvelope, Network
    try:
        envelope = TransactionEnvelope.from_xdr(unsigned_xdr, network_passphrase=Network.TESTNET_NETWORK_PASSPHRASE)
        kp = Keypair.from_secret(s.stellar_platform_secret)
        envelope.sign(kp)
        signed_xdr = envelope.to_xdr()
        tx_hash = envelope.hash_hex()
    except Exception as e:
        raise HTTPException(500, f"Platform signing failed: {e}")

    # Step 3: Submit deploy tx to Stellar
    escrow_address = None
    try:
        submit_result = await submit_transaction(signed_xdr)
        escrow_address = submit_result.get("contractId", "")
    except Exception as e:
        raise HTTPException(502, f"Deploy transaction failed: {e}")

    # Store in DB
    conn = db._get_conn()
    escrow_id = None
    if conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO report_escrows (report_type, buyer_stellar, amount_usdc, engagement_id, escrow_contract, status)
                VALUES (%s, %s, %s, %s, %s, 'deployed') RETURNING id
            """, (report_type, buyer_stellar, amount, engagement_id, escrow_address or ""))
            row = cur.fetchone()
            escrow_id = row[0] if row else None

    return {
        "escrow_id": escrow_id,
        "tx_hash": tx_hash,
        "escrow_address": escrow_address,
        "amount_usdc": amount,
        "report_type": report_type,
        "engagement_id": engagement_id,
        "explorer_url": f"https://stellar.expert/explorer/testnet/tx/{tx_hash}" if tx_hash else None,
        "next_step": "fund",
    }


@router.post("/reports/confirm")
async def confirm_and_generate(request: Request):
    """After user funds escrow (or skips if demo), generate report."""
    body = await request.json()
    escrow_id = body.get("escrow_id")
    signed_xdr = body.get("signed_xdr", "")

    if not escrow_id:
        raise HTTPException(400, "escrow_id required")

    conn = db._get_conn()
    if not conn:
        raise HTTPException(503, "DB unavailable")

    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM report_escrows WHERE id=%s AND status IN ('deployed','pending')", (escrow_id,))
        escrow = cur.fetchone()
    if not escrow:
        raise HTTPException(404, "Escrow not found or already processed")

    # Submit fund XDR if provided (user signed the fund tx)
    fund_tx_hash = None
    if signed_xdr:
        try:
            from app.trustless_escrow import submit_transaction
            result = await submit_transaction(signed_xdr)
            fund_tx_hash = result.get("hash") or result.get("tx_hash") or result.get("id", "")
        except Exception as e:
            error_msg = str(e)
            # Return structured error with details
            return JSONResponse(status_code=502, content={
                "error": "fund_failed",
                "message": f"Fund transaction failed: {error_msg}",
                "escrow_id": escrow_id,
                "hint": "Ensure your Stellar wallet has USDC testnet tokens and a USDC trustline.",
            })

    # Mark funded
    with conn.cursor() as cur:
        cur.execute("UPDATE report_escrows SET status='funded', funded_at=NOW() WHERE id=%s", (escrow_id,))

    # Generate report inline
    try:
        from app.report_generator import generate_premium_report
        report_data = await generate_premium_report(escrow["report_type"])
    except Exception as e:
        logger.error(f"Report generation failed for escrow {escrow_id}: {e}")
        raise HTTPException(503, "Report generation temporarily unavailable. Will retry automatically.")

    # Store report and mark delivered
    import json as _json
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE report_escrows SET status='delivered', report_data=%s, delivered_at=NOW() WHERE id=%s",
            (_json.dumps(report_data), escrow_id))

    return {
        "status": "delivered",
        "report": report_data,
        "escrow_id": escrow_id,
        "fund_tx_hash": fund_tx_hash,
        "fund_explorer_url": f"https://stellar.expert/explorer/testnet/tx/{fund_tx_hash}" if fund_tx_hash else None,
    }


@router.get("/reports/{escrow_id}")
async def get_report(escrow_id: int, buyer_stellar: str = Query(...)):
    """Retrieve a purchased report."""
    conn = db._get_conn()
    if not conn:
        raise HTTPException(503, "DB unavailable")
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM report_escrows WHERE id=%s AND buyer_stellar=%s", (escrow_id, buyer_stellar))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    if row["status"] == "pending":
        raise HTTPException(402, "Not yet funded")
    if row["status"] == "funded":
        return {"status": "generating", "message": "Report is being generated. Please wait."}
    return {"status": row["status"], "report": row.get("report_data"), "delivered_at": str(row.get("delivered_at", ""))}
