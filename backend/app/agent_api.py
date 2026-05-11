"""Agent API v2 — structured endpoints for AI agent consumption."""
import logging
from fastapi import APIRouter, Query

from app import db
from app.db import _get_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agent", tags=["agent"])


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
    """Get user's agent config + learned preferences."""
    agent = db.get_user_agent(address)
    if not agent:
        return {"agent": None, "learned": db.compute_preferences_from_swipes(address)}
    return {"agent": agent, "learned": agent.get("learned_preferences") or db.compute_preferences_from_swipes(address)}


@router.put("/my-agent")
async def upsert_my_agent(request: dict):
    """Create or update user's agent config."""
    address = request.get("address", "")
    if not address:
        return {"error": "address required"}
    config = {k: v for k, v in request.items() if k != "address"}
    agent = db.upsert_user_agent(address, config)
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


@router.post("/my-agent/toggle")
async def toggle_agent(request: dict):
    """Activate or deactivate user's agent."""
    address = request.get("address", "")
    if not address:
        return {"error": "address required"}
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
