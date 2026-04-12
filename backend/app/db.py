"""Supabase/Postgres signal storage — minimal client."""
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
