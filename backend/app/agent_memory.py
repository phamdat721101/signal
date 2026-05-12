"""Track prediction accuracy for the multi-agent analysis engine."""
import logging
from datetime import datetime, timezone, timedelta
import httpx
from psycopg2.extras import RealDictCursor
from app.db import _get_conn

logger = logging.getLogger(__name__)


def ensure_table():
    try:
        conn = _get_conn()
        if not conn: return
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS agent_predictions (
                id SERIAL PRIMARY KEY, token_symbol TEXT NOT NULL, verdict TEXT NOT NULL,
                confidence INTEGER NOT NULL, entry_price DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(), resolved_at TIMESTAMPTZ,
                outcome_pct DOUBLE PRECISION, was_correct BOOLEAN)""")
    except Exception as e:
        logger.error("ensure_table: %s", e)


def store_prediction(card: dict):
    try:
        conn = _get_conn()
        if not conn: return
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_predictions (token_symbol,verdict,confidence,entry_price) VALUES (%s,%s,%s,%s)",
                (card["token_symbol"], card["verdict"], card.get("risk_score", 50), card.get("price", 0)))
    except Exception as e:
        logger.error("store_prediction: %s", e)


def resolve_predictions():
    try:
        conn = _get_conn()
        if not conn: return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,token_symbol,verdict,entry_price FROM agent_predictions WHERE resolved_at IS NULL AND created_at < %s",
                (cutoff,))
            rows = cur.fetchall()
        if not rows: return
        symbols = {r["token_symbol"] for r in rows}
        prices = _fetch_resolution_prices(symbols)
        with conn.cursor() as cur:
            for r in rows:
                current = prices.get(r["token_symbol"])
                if not current or not r["entry_price"]: continue
                pct = (current - r["entry_price"]) / r["entry_price"] * 100
                correct = (pct > 0) if r["verdict"] == "APE" else (pct < 0)
                cur.execute("UPDATE agent_predictions SET resolved_at=NOW(),outcome_pct=%s,was_correct=%s WHERE id=%s",
                            (round(pct, 2), correct, r["id"]))
        # Also resolve event_outcomes from sentiment_engine
        _resolve_event_outcomes(prices)
    except Exception as e:
        logger.error("resolve_predictions: %s", e)


def _fetch_resolution_prices(symbols: set) -> dict[str, float]:
    """DexScreener first (free), CoinGecko fallback for missing."""
    prices = {}
    for sym in symbols:
        try:
            resp = httpx.get(f"https://api.dexscreener.com/latest/dex/search?q={sym}", timeout=8)
            if resp.status_code == 200:
                pairs = resp.json().get("pairs", [])
                if pairs:
                    prices[sym] = float(pairs[0].get("priceUsd", 0))
        except Exception:
            pass
    missing = symbols - set(prices.keys())
    if missing:
        try:
            ids = ",".join(s.lower() for s in missing)
            data = httpx.get(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd", timeout=10).json()
            for sym in missing:
                p = data.get(sym.lower(), {}).get("usd")
                if p: prices[sym] = p
        except Exception:
            pass
    return prices


def _resolve_event_outcomes(prices: dict[str, float]):
    """Resolve pending event_outcomes with current prices."""
    conn = _get_conn()
    if not conn: return
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, token_symbol, price_at_event FROM event_outcomes "
                "WHERE resolved_at IS NULL AND created_at < NOW() - INTERVAL '24 hours'")
            rows = cur.fetchall()
        if not rows: return
        with conn.cursor() as cur:
            for r in rows:
                current = prices.get(r["token_symbol"])
                if not current or not r["price_at_event"]: continue
                pct = (current - r["price_at_event"]) / r["price_at_event"] * 100
                cur.execute(
                    "UPDATE event_outcomes SET resolved_at=NOW(), price_after_24h=%s, outcome_pct=%s, was_profitable=%s WHERE id=%s",
                    (current, round(pct, 2), pct > 0, r["id"]))
        logger.info("Resolved %d event outcomes", len(rows))
    except Exception as e:
        logger.warning("_resolve_event_outcomes: %s", e)


def get_accuracy_context(symbol: str) -> str:
    try:
        conn = _get_conn()
        if not conn: return ""
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT was_correct,outcome_pct FROM agent_predictions WHERE token_symbol=%s AND resolved_at IS NOT NULL ORDER BY resolved_at DESC LIMIT 5",
                (symbol,))
            rows = cur.fetchall()
        if not rows: return ""
        correct = sum(1 for r in rows if r["was_correct"])
        avg_pct = sum(r["outcome_pct"] for r in rows) / len(rows)
        return f"Last {len(rows)} calls on {symbol}: {correct}/{len(rows)} correct, avg {avg_pct:+.1f}%"
    except Exception as e:
        logger.error("get_accuracy_context: %s", e)
        return ""
