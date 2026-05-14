"""Agent API v2 — structured endpoints for AI agent consumption."""
import logging
from fastapi import APIRouter, Query, Request

from app import db
from app.db import _get_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agent", tags=["agent"])

ALLOWED_AGENT_FIELDS = {"strategy", "max_position_usd", "tokens_whitelist", "tokens_blacklist",
                         "min_confidence", "auto_execute", "risk_tolerance", "take_profit_pct",
                         "stop_loss_pct", "is_active"}


def _verify_ownership(body_address: str, header_address: str | None):
    """Verify caller owns the address via X-Wallet-Address header."""
    if not header_address or body_address.lower() != header_address.lower():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="X-Wallet-Address header must match request address")


@router.get("/decisions")
async def get_decisions(limit: int = Query(default=10, le=50)):
    """Structured trading decisions for AI agents."""
    cards, _ = db.get_cards(0, limit)
    decisions = []
    for c in cards:
        entry = c.get("price", 0)
        if entry <= 0:
            continue
        is_bull = c.get("verdict") == "APE"
        decisions.append({
            "id": c["id"],
            "type": "liquidity" if c.get("card_type") == "pool" else "trading",
            "token": c["token_symbol"],
            "action": c.get("verdict", "HOLD"),
            "confidence": max(10, 100 - (c.get("risk_score") or 50)),
            "entry": round(entry, 6),
            "target": round(entry * (1.015 if is_bull else 0.985), 6),
            "stop": round(entry * (0.985 if is_bull else 1.015), 6),
            "reasoning": c.get("verdict_reason", ""),
            "rarity": c.get("rarity", "common"),
            "track_record": _get_token_track_record(c["token_symbol"]),
        })
    return {"decisions": decisions, "total": len(decisions)}


def _get_token_track_record(symbol: str) -> dict:
    """Quick accuracy lookup for a token."""
    conn = _get_conn()
    if not conn:
        return {"win_rate": 0, "sample_size": 0}
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as wins "
            "FROM agent_predictions WHERE token_symbol=%s AND resolved_at IS NOT NULL",
            (symbol,))
        row = cur.fetchone()
    total = row["total"] or 0
    wins = row["wins"] or 0
    return {"win_rate": round(wins / total * 100, 1) if total > 0 else 0, "sample_size": total}


@router.get("/prices")
async def get_prices(symbols: str = Query(..., description="Comma-separated symbols")):
    """Aggregated prices from best available source."""
    from app.price_feed import get_prices as fetch_prices
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return {"prices": fetch_prices(symbol_list)}


@router.get("/pools")
async def get_pools(limit: int = Query(default=10, le=50)):
    """LP advisory opportunities."""
    cards, total = db.get_cards(0, limit, card_type="pool")
    return {"pools": cards, "total": total}


@router.get("/track-record")
async def get_track_record():
    """Historical accuracy stats."""
    conn = _get_conn()
    if not conn:
        return {"overall": {"total": 0, "wins": 0, "win_rate": 0}, "per_token": {}}
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) as total, SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as wins FROM agent_predictions WHERE resolved_at IS NOT NULL")
        overall = cur.fetchone()
        cur.execute("""
            SELECT token_symbol, COUNT(*) as total, SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as wins,
                   ROUND(AVG(outcome_pct)::numeric, 2) as avg_pnl
            FROM agent_predictions WHERE resolved_at IS NOT NULL
            GROUP BY token_symbol HAVING COUNT(*) >= 3 ORDER BY COUNT(*) DESC LIMIT 20
        """)
        rows = cur.fetchall()
    total = overall["total"] or 0
    wins = overall["wins"] or 0
    per_token = {r["token_symbol"]: {"total": r["total"], "wins": r["wins"] or 0,
                 "win_rate": round((r["wins"] or 0) / r["total"] * 100, 1), "avg_pnl": float(r["avg_pnl"] or 0)}
                 for r in rows}
    return {
        "overall": {"total": total, "wins": wins, "win_rate": round(wins / max(total, 1) * 100, 1)},
        "per_token": per_token,
    }


@router.get("/context")
async def get_context():
    """Market context: SoSoValue data + oracle mood."""
    from app.sosovalue_client import get_full_context
    from app.degen_oracle import get_current_mood
    return {"sosovalue": get_full_context(), "oracle_mood": get_current_mood()}


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
    """Subscribe to a signal — deploys escrow, returns unsigned XDR for funding."""
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

    from app.trustless_escrow import deploy_escrow, fund_escrow
    from app.config import get_settings as _gs
    platform_addr = _gs().stellar_platform_address
    if not platform_addr:
        return {"error": "Stellar platform not configured"}

    try:
        deploy_result = await deploy_escrow(subscriber_stellar, platform_addr, amount, card["id"])
        escrow_address = deploy_result.get("contractId", deploy_result.get("address", ""))
    except Exception as e:
        return {"error": f"Escrow deploy failed: {e}"}

    conn = db._get_conn()
    if conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO signal_escrows (signal_id, subscriber_stellar, provider_stellar, escrow_contract, amount_usdc, status) VALUES (%s,%s,%s,%s,%s,'deployed')",
                (card["id"], subscriber_stellar, platform_addr, escrow_address, amount))
        db._put_conn(conn)

    try:
        fund_result = await fund_escrow(escrow_address, subscriber_stellar)
    except Exception as e:
        return {"escrow_address": escrow_address, "error": f"Fund XDR failed: {e}"}

    return {"escrow_address": escrow_address, "unsigned_xdr": fund_result.get("unsignedXDR", ""), "amount_usdc": amount, "signal_id": card["id"]}


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
