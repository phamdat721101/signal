"""Sentiment Engine — per-token sentiment scoring with event tracking for AI agent learning.

Aggregates: news sentiment + ETF flows + whale movements + macro events → composite score.
Persists to DB for event-outcome correlation.
"""

import logging
import time
from app.db import _get_conn

log = logging.getLogger(__name__)

EVENT_TYPES = ("etf_inflow", "etf_outflow", "macro_event", "whale_buy",
               "news_bullish", "news_bearish", "sector_rotation")

_sentiment_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 120  # 2 min


def ensure_tables():
    """Create sentiment tables if not exist."""
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '5s'")
            cur.execute("""CREATE TABLE IF NOT EXISTS token_sentiment (
                id SERIAL PRIMARY KEY,
                token_symbol TEXT NOT NULL,
                score INTEGER NOT NULL,
                components JSONB DEFAULT '{}',
                events TEXT[] DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS event_outcomes (
                id SERIAL PRIMARY KEY,
                token_symbol TEXT NOT NULL,
                event_type TEXT NOT NULL,
                sentiment_at_event INTEGER DEFAULT 0,
                price_at_event DOUBLE PRECISION DEFAULT 0,
                price_after_24h DOUBLE PRECISION,
                outcome_pct DOUBLE PRECISION,
                was_profitable BOOLEAN,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                resolved_at TIMESTAMPTZ)""")
            cur.execute("RESET statement_timeout")
    except Exception as e:
        log.warning("ensure_tables: %s", e)


def compute_sentiment(symbol: str) -> dict:
    """Compute composite sentiment for a token. Returns {score, components, events, direction}."""
    now = time.time()
    cached = _sentiment_cache.get(symbol)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    components = {}
    events = []

    # 1. News sentiment
    from app.news_aggregator import get_token_news, get_market_sentiment
    token_news = get_token_news(symbol, 5)
    if token_news:
        components["news"] = int(sum(n["sentiment_score"] for n in token_news) / len(token_news))
        if components["news"] > 30:
            events.append("news_bullish")
        elif components["news"] < -30:
            events.append("news_bearish")
    else:
        # Fallback to market-wide sentiment
        market = get_market_sentiment()
        components["news"] = market["score"]

    # 2. ETF flows (BTC/ETH only)
    from app.sosovalue_client import get_etf_flows, _is_enabled
    if _is_enabled() and symbol in ("BTC", "ETH"):
        flows = get_etf_flows()
        flow = flows.get(f"{symbol.lower()}_net_flow", 0)
        if flow:
            # Normalize: $500M = +100, -$500M = -100
            components["etf"] = max(-100, min(100, int(flow / 5_000_000)))
            if flow > 50_000_000:
                events.append("etf_inflow")
            elif flow < -50_000_000:
                events.append("etf_outflow")

    # 3. Whale movements
    from app.sosovalue_client import get_whale_deltas
    if symbol == "BTC":
        deltas = get_whale_deltas()
        if deltas:
            net = sum(d["change_btc"] for d in deltas[:5])
            components["whale"] = max(-100, min(100, int(net / 100)))  # 100 BTC = +100
            if net > 50:
                events.append("whale_buy")

    # 4. Macro events
    from app.sosovalue_client import get_macro_events
    if _is_enabled():
        macro = get_macro_events()
        if macro:
            components["macro"] = -20  # Macro events = uncertainty = slightly bearish
            events.append("macro_event")

    # Composite: weighted average
    weights = {"news": 0.4, "etf": 0.3, "whale": 0.15, "macro": 0.15}
    total_weight = sum(weights.get(k, 0) for k in components)
    if total_weight > 0:
        score = int(sum(components.get(k, 0) * weights.get(k, 0) for k in components) / total_weight)
    else:
        score = 0

    direction = "bullish" if score > 20 else "bearish" if score < -20 else "neutral"
    result = {"score": max(-100, min(100, score)), "components": components, "events": events, "direction": direction}
    _sentiment_cache[symbol] = (now, result)
    return result


def store_sentiment(symbol: str, sentiment: dict):
    """Persist sentiment snapshot to DB."""
    conn = _get_conn()
    if not conn:
        return
    try:
        import json
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO token_sentiment (token_symbol, score, components, events) VALUES (%s,%s,%s,%s)",
                (symbol, sentiment["score"], json.dumps(sentiment["components"]), sentiment["events"]))
    except Exception as e:
        log.warning("store_sentiment failed: %s", e)


def record_event(symbol: str, event_type: str, sentiment_score: int, price: float):
    """Record an event for later outcome correlation."""
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO event_outcomes (token_symbol, event_type, sentiment_at_event, price_at_event) VALUES (%s,%s,%s,%s)",
                (symbol, event_type, sentiment_score, price))
    except Exception as e:
        log.warning("record_event failed: %s", e)


def get_event_patterns(symbol: str | None = None) -> dict:
    """Get event-outcome patterns for agent learning. Returns {event_type: {count, win_rate, avg_pnl}}."""
    conn = _get_conn()
    if not conn:
        return {}
    from psycopg2.extras import RealDictCursor
    try:
        where = "WHERE resolved_at IS NOT NULL"
        params: list = []
        if symbol:
            where += " AND token_symbol = %s"
            params.append(symbol)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT event_type, COUNT(*) as count,
                    SUM(CASE WHEN was_profitable THEN 1 ELSE 0 END) as wins,
                    ROUND(AVG(outcome_pct)::numeric, 2) as avg_pnl
                FROM event_outcomes {where}
                GROUP BY event_type HAVING COUNT(*) >= 3
            """, params)
            rows = cur.fetchall()
        return {r["event_type"]: {
            "count": r["count"], "win_rate": round((r["wins"] or 0) / r["count"] * 100, 1),
            "avg_pnl": float(r["avg_pnl"] or 0)
        } for r in rows}
    except Exception as e:
        log.warning("get_event_patterns failed: %s", e)
        return {}


def refresh_sentiment():
    """Called by scheduler. Compute and store sentiment for active tokens."""
    ensure_tables()
    from app.db import _get_conn
    conn = _get_conn()
    if not conn:
        return
    from psycopg2.extras import RealDictCursor
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT DISTINCT token_symbol FROM cards WHERE status='active' AND created_at > NOW() - INTERVAL '6 hours' LIMIT 20")
            symbols = [r["token_symbol"] for r in cur.fetchall()]
        for sym in symbols:
            if sym in ("INSIGHT",) or "." in sym:
                continue
            sentiment = compute_sentiment(sym)
            store_sentiment(sym, sentiment)
        if symbols:
            log.info("Sentiment refreshed for %d tokens", len(symbols))
    except Exception as e:
        log.warning("refresh_sentiment failed: %s", e)
