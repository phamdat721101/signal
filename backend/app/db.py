"""Supabase/Postgres signal storage — minimal client."""
import json
import logging
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import get_settings

logger = logging.getLogger(__name__)

_conn = None


def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        settings = get_settings()
        if not settings.database_url:
            return None
        # Strip pgbouncer param not supported by psycopg2
        url = settings.database_url.split("?")[0]
        _conn = psycopg2.connect(url)
        _conn.autocommit = True
    return _conn


def init_db():
    """Create signals table if not exists."""
    conn = _get_conn()
    if not conn:
        logger.warning("DATABASE_URL not set — Supabase disabled")
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id SERIAL PRIMARY KEY,
                asset TEXT NOT NULL,
                symbol TEXT NOT NULL DEFAULT '',
                is_bull BOOLEAN NOT NULL,
                confidence INTEGER NOT NULL,
                target_price TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                exit_price TEXT NOT NULL DEFAULT '0',
                timestamp INTEGER NOT NULL,
                resolved BOOLEAN NOT NULL DEFAULT FALSE,
                creator TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                pattern TEXT DEFAULT '',
                analysis TEXT DEFAULT '',
                timeframe TEXT DEFAULT '',
                stop_loss TEXT DEFAULT '0',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    logger.info("Supabase signals table ready")
    # Cards table (Ape or Fade)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                token_symbol TEXT NOT NULL,
                token_name TEXT NOT NULL,
                chain TEXT DEFAULT 'initia',
                hook TEXT NOT NULL DEFAULT '',
                roast TEXT NOT NULL DEFAULT '',
                metrics JSONB DEFAULT '[]',
                image_url TEXT DEFAULT '',
                ai_image_prompt TEXT DEFAULT '',
                price DOUBLE PRECISION DEFAULT 0,
                price_change_24h DOUBLE PRECISION DEFAULT 0,
                volume_24h DOUBLE PRECISION DEFAULT 0,
                market_cap DOUBLE PRECISION DEFAULT 0,
                coingecko_id TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS swipes (
                id SERIAL PRIMARY KEY,
                card_id INTEGER NOT NULL,
                user_address TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Migrate: add new columns if missing
        for col, defn in [
            ("verdict", "TEXT DEFAULT 'DYOR'"),
            ("verdict_reason", "TEXT DEFAULT ''"),
            ("risk_level", "TEXT DEFAULT 'MID'"),
            ("risk_score", "INTEGER DEFAULT 50"),
            ("notification_hook", "TEXT DEFAULT ''"),
            ("signals", "JSONB DEFAULT '[]'"),
            ("expires_at", "TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '4 hours')"),
        ]:
            try:
                cur.execute(f"ALTER TABLE cards ADD COLUMN IF NOT EXISTS {col} {defn}")
            except Exception:
                pass
    logger.info("Cards + swipes tables ready")


def insert_signal(signal: dict) -> int:
    """Insert a signal, return its ID."""
    conn = _get_conn()
    if not conn:
        return -1
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO signals
               (asset, symbol, is_bull, confidence, target_price, entry_price, exit_price,
                timestamp, resolved, creator, provider, pattern, analysis, timeframe, stop_loss)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (signal.get("asset", ""), signal.get("symbol", ""),
             signal.get("isBull", True), signal.get("confidence", 0),
             str(signal.get("targetPrice", "0")), str(signal.get("entryPrice", "0")),
             str(signal.get("exitPrice", "0")), signal.get("timestamp", int(time.time())),
             signal.get("resolved", False), signal.get("creator", ""),
             signal.get("provider", ""), signal.get("pattern", ""),
             signal.get("analysis", ""), signal.get("timeframe", ""),
             str(signal.get("stopLoss", "0")))
        )
        return cur.fetchone()[0]


def get_signals(offset: int = 0, limit: int = 100, provider: str | None = None) -> tuple[list[dict], int]:
    """Fetch signals with optional provider filter. Returns (signals, total)."""
    conn = _get_conn()
    if not conn:
        return [], 0
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        where = "WHERE provider = %s" if provider else ""
        params = (provider,) if provider else ()

        cur.execute(f"SELECT COUNT(*) as cnt FROM signals {where}", params)
        total = cur.fetchone()["cnt"]

        cur.execute(
            f"""SELECT * FROM signals {where}
                ORDER BY timestamp DESC LIMIT %s OFFSET %s""",
            (*params, limit, offset)
        )
        rows = cur.fetchall()
    return [_row_to_signal(r) for r in rows], total


def get_signal_by_id(signal_id: int) -> dict | None:
    conn = _get_conn()
    if not conn:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM signals WHERE id = %s", (signal_id,))
        row = cur.fetchone()
    return _row_to_signal(row) if row else None


def get_unresolved_signals(cutoff_timestamp: int) -> list[dict]:
    """Return unresolved signals older than cutoff_timestamp."""
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM signals WHERE resolved = FALSE AND timestamp < %s",
            (cutoff_timestamp,)
        )
        return [_row_to_signal(r) for r in cur.fetchall()]


def resolve_signal(signal_id: int, exit_price: str) -> bool:
    conn = _get_conn()
    if not conn:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signals SET exit_price = %s, resolved = TRUE WHERE id = %s",
            (exit_price, signal_id)
        )
        return cur.rowcount > 0


def _row_to_signal(row: dict) -> dict:
    """Convert DB row to signal dict matching frontend schema."""
    return {
        "id": row["id"],
        "asset": row["asset"],
        "isBull": row["is_bull"],
        "confidence": row["confidence"],
        "targetPrice": row["target_price"],
        "entryPrice": row["entry_price"],
        "exitPrice": row["exit_price"],
        "timestamp": row["timestamp"],
        "resolved": row["resolved"],
        "creator": row["creator"],
        "provider": row["provider"],
        "symbol": row["symbol"],
        "pattern": row.get("pattern", ""),
        "analysis": row.get("analysis", ""),
        "timeframe": row.get("timeframe", ""),
        "stopLoss": row.get("stop_loss", "0"),
    }


# ─── Cards (Ape or Fade) ────────────────────────────────────

def insert_card(card: dict) -> int:
    conn = _get_conn()
    if not conn:
        return -1
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO cards
               (token_symbol, token_name, chain, hook, roast, metrics, image_url,
                ai_image_prompt, price, price_change_24h, volume_24h, market_cap, coingecko_id,
                verdict, verdict_reason, risk_level, risk_score, notification_hook, signals)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (card.get("token_symbol", ""), card.get("token_name", ""),
             card.get("chain", "initia"), card.get("hook", ""), card.get("roast", ""),
             json.dumps(card.get("metrics", [])), card.get("image_url", ""),
             card.get("ai_image_prompt", ""), card.get("price", 0),
             card.get("price_change_24h", 0), card.get("volume_24h", 0),
             card.get("market_cap", 0), card.get("coingecko_id", ""),
             card.get("verdict", "DYOR"), card.get("verdict_reason", ""),
             card.get("risk_level", "MID"), card.get("risk_score", 50),
             card.get("notification_hook", ""), json.dumps(card.get("signals", [])))
        )
        return cur.fetchone()[0]


def get_cards(offset: int = 0, limit: int = 20, status: str = "active") -> tuple[list[dict], int]:
    conn = _get_conn()
    if not conn:
        return [], 0
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM cards WHERE status = %s", (status,))
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT * FROM cards WHERE status = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (status, limit, offset)
        )
        rows = cur.fetchall()
    return [_row_to_card(r) for r in rows], total


def get_card_by_id(card_id: int) -> dict | None:
    conn = _get_conn()
    if not conn:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
        row = cur.fetchone()
    return _row_to_card(row) if row else None


def get_existing_coingecko_ids() -> set[str]:
    conn = _get_conn()
    if not conn:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT coingecko_id FROM cards")
        return {r[0] for r in cur.fetchall()}


def record_swipe(card_id: int, user_address: str, action: str) -> int:
    conn = _get_conn()
    if not conn:
        return -1
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO swipes (card_id, user_address, action) VALUES (%s,%s,%s) RETURNING id",
            (card_id, user_address, action)
        )
        return cur.fetchone()[0]


def get_user_swipes(user_address: str, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    conn = _get_conn()
    if not conn:
        return [], 0
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM swipes WHERE user_address = %s", (user_address,))
        total = cur.fetchone()["cnt"]
        cur.execute(
            """SELECT s.*, c.token_symbol, c.token_name, c.price, c.price_change_24h, c.hook
               FROM swipes s JOIN cards c ON s.card_id = c.id
               WHERE s.user_address = %s ORDER BY s.created_at DESC LIMIT %s OFFSET %s""",
            (user_address, limit, offset)
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows], total


def get_leaderboard(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT user_address,
                      COUNT(*) as total_trades,
                      COUNT(*) FILTER (WHERE action = 'ape') as apes,
                      COUNT(*) FILTER (WHERE action = 'fade') as fades
               FROM swipes GROUP BY user_address
               ORDER BY COUNT(*) FILTER (WHERE action = 'ape') DESC LIMIT %s""",
            (limit,)
        )
        return [dict(r) for r in cur.fetchall()]


def _row_to_card(row: dict) -> dict:
    return {
        "id": row["id"],
        "token_symbol": row["token_symbol"],
        "token_name": row["token_name"],
        "chain": row["chain"],
        "hook": row["hook"],
        "roast": row["roast"],
        "metrics": row["metrics"] if isinstance(row["metrics"], list) else json.loads(row.get("metrics", "[]")),
        "image_url": row["image_url"],
        "ai_image_prompt": row.get("ai_image_prompt", ""),
        "price": row["price"],
        "price_change_24h": row["price_change_24h"],
        "volume_24h": row["volume_24h"],
        "market_cap": row["market_cap"],
        "coingecko_id": row.get("coingecko_id", ""),
        "status": row["status"],
        "created_at": str(row["created_at"]),
        "verdict": row.get("verdict", "DYOR"),
        "verdict_reason": row.get("verdict_reason", ""),
        "risk_level": row.get("risk_level", "MID"),
        "risk_score": row.get("risk_score", 50),
        "notification_hook": row.get("notification_hook", ""),
        "signals": row.get("signals", []) if isinstance(row.get("signals"), list) else json.loads(row.get("signals", "[]")),
        "expires_at": str(row["expires_at"]) if row.get("expires_at") else None,
    }
