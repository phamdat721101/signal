"""Supabase/Postgres signal storage — minimal client."""
import json
import logging
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import get_settings

logger = logging.getLogger(__name__)

_pool = None


def _get_conn():
    """Get a DB connection. Creates new one if needed."""
    global _pool
    settings = get_settings()
    if not settings.database_url:
        return None
    url = settings.database_url.split("?")[0]
    try:
        conn = psycopg2.connect(url, connect_timeout=5)
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.warning(f"DB connection failed: {e}")
        return None


def _put_conn(conn):
    """Close connection after use."""
    if conn:
        try:
            conn.close()
        except Exception:
            pass


def _get_read_conn():
    return _get_conn()


def init_db():
    """Create tables if not exists. Skips if already initialized."""
    conn = _get_conn()
    if not conn:
        logger.warning("DATABASE_URL not set — Supabase disabled")
        return
    # Fast check: if signals table exists, skip all CREATE statements
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM signals LIMIT 1")
        logger.info("DB tables already exist — skipping init")
        return
    except Exception:
        pass  # Table doesn't exist, proceed with creation
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '10s'")
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS x402_settlements (
                payload_hash TEXT PRIMARY KEY,
                resource     TEXT NOT NULL,
                payer        TEXT,
                amount       TEXT,
                network      TEXT,
                tx_hash      TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                retries      INTEGER DEFAULT 0,
                last_error   TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                settled_at   TIMESTAMPTZ
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS x402_settlements_status_idx
              ON x402_settlements (status, created_at)
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
            ("on_chain_signal_id", "INTEGER DEFAULT NULL"),
            ("sparkline", "JSONB DEFAULT '[]'"),
            ("patterns", "JSONB DEFAULT '[]'"),
            ("ohlc", "JSONB DEFAULT '[]'"),
            ("source", "TEXT DEFAULT 'ai'"),
            ("provider", "TEXT DEFAULT ''"),
            ("signal_id", "INTEGER DEFAULT NULL"),
            ("research_summary", "JSONB DEFAULT '{}'"),
        ]:
            try:
                cur.execute(f"ALTER TABLE cards ADD COLUMN IF NOT EXISTS {col} {defn}")
            except Exception:
                pass
    # Signals table migrations
    with conn.cursor() as cur:
        for col, defn in [
            ("resolution_type", "TEXT DEFAULT NULL"),
        ]:
            try:
                cur.execute(f"ALTER TABLE signals ADD COLUMN IF NOT EXISTS {col} {defn}")
            except Exception:
                pass
    logger.info("Cards + swipes tables ready")
    # Trades table (Ape trade execution)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                card_id INTEGER NOT NULL,
                user_address TEXT NOT NULL,
                token_symbol TEXT NOT NULL,
                token_name TEXT NOT NULL DEFAULT '',
                entry_price DOUBLE PRECISION NOT NULL,
                amount_usd DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                token_amount DOUBLE PRECISION NOT NULL,
                tx_hash TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'completed',
                exit_price DOUBLE PRECISION,
                pnl_usd DOUBLE PRECISION,
                pnl_pct DOUBLE PRECISION,
                resolved BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    logger.info("Trades table ready")
    # SoDex trade columns
    with conn.cursor() as cur:
        for col, defn in [
            ("sodex_order_id", "TEXT"),
            ("execution_type", "TEXT DEFAULT 'simulated'"),
        ]:
            try:
                cur.execute(f"ALTER TABLE trades ADD COLUMN IF NOT EXISTS {col} {defn}")
            except Exception:
                pass
    # Provider marketplace tables
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS providers (address TEXT PRIMARY KEY, name TEXT, description TEXT, avatar_url TEXT, win_rate REAL DEFAULT 0, total_signals INTEGER DEFAULT 0, created_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("""CREATE TABLE IF NOT EXISTS provider_follows (id SERIAL PRIMARY KEY, user_address TEXT NOT NULL, provider_address TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(user_address, provider_address))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (id SERIAL PRIMARY KEY, user_address TEXT NOT NULL, subscription JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(user_address))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS referrals (id SERIAL PRIMARY KEY, referrer TEXT NOT NULL, referred TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(referred))""")
    logger.info("Provider marketplace tables ready")
    # Daily swipes table (premium gate)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_swipes (
                id SERIAL PRIMARY KEY,
                user_address TEXT NOT NULL,
                swipe_date DATE NOT NULL DEFAULT CURRENT_DATE,
                count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_address, swipe_date)
            )
        """)
        # Energy-refill ledger — tx_hash is the idempotency key. Same hash on
        # two refill calls = single row. Mirrors x402_settlements.payload_hash.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS energy_refills (
                tx_hash      TEXT PRIMARY KEY,
                user_address TEXT NOT NULL,
                session_id   BIGINT,
                amount_iusd  NUMERIC,
                refilled_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS energy_refills_user_idx
              ON energy_refills (user_address, refilled_at DESC)
        """)
    logger.info("Daily swipes table ready")
    # New tables for SosoValue integration
    with conn.cursor() as cur:
        for col, defn in [
            ("card_type", "TEXT DEFAULT 'trading'"),
            ("verdict", "TEXT DEFAULT ''"),
            ("signals", "JSONB DEFAULT '[]'"),
            ("institutional_context", "JSONB DEFAULT '{}'"),
            ("expires_at", "TIMESTAMPTZ"),
        ]:
            try:
                cur.execute(f"ALTER TABLE cards ADD COLUMN IF NOT EXISTS {col} {defn}")
            except Exception:
                pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS oracle_takes (
                id SERIAL PRIMARY KEY,
                mood TEXT NOT NULL,
                take TEXT NOT NULL,
                emoji TEXT DEFAULT '🔮',
                context JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    logger.info("oracle_takes table ready")
    # Report escrows table
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS report_escrows (
                id SERIAL PRIMARY KEY,
                report_type TEXT NOT NULL,
                buyer_stellar TEXT NOT NULL,
                escrow_contract TEXT,
                amount_usdc NUMERIC(10,2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                report_data JSONB,
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                engagement_id TEXT UNIQUE,
                funded_at TIMESTAMPTZ,
                delivered_at TIMESTAMPTZ,
                released_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    logger.info("report_escrows table ready")
    init_user_agents_table()


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
        "resolutionType": row.get("resolution_type"),
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
                verdict, verdict_reason, risk_level, risk_score, notification_hook, signals,
                sparkline, patterns, ohlc, source, provider, signal_id, institutional_context, card_type, research_summary)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (card.get("token_symbol", ""), card.get("token_name", ""),
             card.get("chain", "initia"), card.get("hook", ""), card.get("roast", ""),
             json.dumps(card.get("metrics", [])), card.get("image_url", ""),
             card.get("ai_image_prompt", ""), card.get("price", 0),
             card.get("price_change_24h", 0), card.get("volume_24h", 0),
             card.get("market_cap", 0), card.get("coingecko_id", ""),
             card.get("verdict", "DYOR"), card.get("verdict_reason", ""),
             card.get("risk_level", "MID"), card.get("risk_score", 50),
             card.get("notification_hook", ""), json.dumps(card.get("signals", [])),
             json.dumps(card.get("sparkline", [])), json.dumps(card.get("patterns", [])),
             json.dumps(card.get("ohlc", [])),
             card.get("source", "ai"), card.get("provider", ""),
             card.get("signal_id"),
             json.dumps(card.get("institutional_context", [])),
             card.get("card_type", "trading"),
             json.dumps(card.get("research_summary", {})))
        )
        return cur.fetchone()[0]


def get_cards(offset: int = 0, limit: int = 20, status: str = "active", card_type: str | None = None) -> tuple[list[dict], int]:
    conn = _get_read_conn()
    if not conn:
        return [], 0
    where = "WHERE status = %s AND (expires_at > NOW() OR expires_at IS NULL)"
    params: list = [status]
    if card_type:
        where += " AND card_type = %s"
        params.append(card_type)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"SELECT COUNT(*) as cnt FROM cards {where}", params)
        total = cur.fetchone()["cnt"]
        cur.execute(
            f"SELECT * FROM cards {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (*params, limit, offset)
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
        cur.execute("SELECT DISTINCT coingecko_id FROM cards WHERE status = %s AND created_at > NOW() - INTERVAL '2 hours'", ("active",))
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


def update_card_signal_id(card_id: int, signal_id: int):
    conn = _get_conn()
    if not conn:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE cards SET on_chain_signal_id = %s WHERE id = %s", (signal_id, card_id))




# ─── Trades (Ape Trade Execution) ────────────────────────────

def insert_trade(trade: dict) -> int:
    conn = _get_conn()
    if not conn:
        return -1
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO trades
               (card_id, user_address, token_symbol, token_name, entry_price,
                amount_usd, token_amount, tx_hash, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (trade["card_id"], trade["user_address"], trade["token_symbol"],
             trade.get("token_name", ""), trade["entry_price"],
             trade["amount_usd"], trade["token_amount"],
             trade.get("tx_hash", ""), trade.get("status", "completed"))
        )
        return cur.fetchone()[0]


def get_user_trades(user_address: str, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    conn = _get_conn()
    if not conn:
        return [], 0
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM trades WHERE user_address = %s", (user_address,))
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT * FROM trades WHERE user_address = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (user_address, limit, offset))
        return [dict(r) for r in cur.fetchall()], total


def get_unresolved_trades() -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM trades WHERE resolved = FALSE")
        return [dict(r) for r in cur.fetchall()]


def update_trade_pnl(trade_id: int, exit_price: float, pnl_usd: float, pnl_pct: float, resolve: bool = False):
    conn = _get_conn()
    if not conn:
        return
    with conn.cursor() as cur:
        if resolve:
            cur.execute(
                "UPDATE trades SET exit_price=%s, pnl_usd=%s, pnl_pct=%s, resolved=TRUE WHERE id=%s",
                (exit_price, pnl_usd, pnl_pct, trade_id))
        else:
            cur.execute(
                "UPDATE trades SET exit_price=%s, pnl_usd=%s, pnl_pct=%s WHERE id=%s",
                (exit_price, pnl_usd, pnl_pct, trade_id))


def get_leaderboard_by_pnl(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT user_address,
                      COUNT(*) as total_trades,
                      COUNT(*) FILTER (WHERE resolved AND pnl_usd > 0) as wins,
                      COUNT(*) FILTER (WHERE resolved AND pnl_usd <= 0) as losses,
                      COALESCE(SUM(pnl_usd) FILTER (WHERE resolved), 0) as total_pnl_usd,
                      CASE WHEN SUM(amount_usd) FILTER (WHERE resolved) > 0
                           THEN COALESCE(SUM(pnl_usd) FILTER (WHERE resolved), 0)
                                / SUM(amount_usd) FILTER (WHERE resolved) * 100
                           ELSE 0 END as total_pnl_pct,
                      CASE WHEN COUNT(*) FILTER (WHERE resolved) > 0
                           THEN COUNT(*) FILTER (WHERE resolved AND pnl_usd > 0)::float
                                / COUNT(*) FILTER (WHERE resolved) * 100
                           ELSE 0 END as win_rate
               FROM trades GROUP BY user_address
               HAVING COUNT(*) FILTER (WHERE resolved) > 0
               ORDER BY COALESCE(SUM(pnl_usd) FILTER (WHERE resolved), 0) DESC
               LIMIT %s""",
            (limit,))
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
        "sparkline": row.get("sparkline", []) if isinstance(row.get("sparkline"), list) else json.loads(row.get("sparkline", "[]")),
        "patterns": row.get("patterns", []) if isinstance(row.get("patterns"), list) else json.loads(row.get("patterns", "[]")),
        "ohlc": row.get("ohlc", []) if isinstance(row.get("ohlc"), list) else json.loads(row.get("ohlc", "[]")),
        "on_chain_signal_id": row.get("on_chain_signal_id"),
        "source": row.get("source", "ai"),
        "provider": row.get("provider", ""),
        "signal_id": row.get("signal_id"),
        "card_type": row.get("card_type", "trading"),
    }


# ─── Daily Swipes (Premium Gate) ─────────────────────────

def get_daily_swipe_count(address: str) -> int:
    conn = _get_conn()
    if not conn or not address:
        return 0
    with conn.cursor() as cur:
        cur.execute("SELECT count FROM daily_swipes WHERE user_address = %s AND swipe_date = CURRENT_DATE", (address,))
        row = cur.fetchone()
        return row[0] if row else 0


def increment_daily_swipes(address: str) -> int:
    conn = _get_conn()
    if not conn or not address:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO daily_swipes (user_address, swipe_date, count) VALUES (%s, CURRENT_DATE, 1)
               ON CONFLICT (user_address, swipe_date) DO UPDATE SET count = daily_swipes.count + 1
               RETURNING count""",
            (address,))
        return cur.fetchone()[0]


# ─── Energy System ───────────────────────────────────────────

PREMIUM_CARD_TYPES = {'macro_desk', 'whale_alert', 'index_battle'}


def get_energy(address: str) -> int:
    """Remaining energy for today."""
    from app.config import get_settings
    return max(0, get_settings().energy_max - get_daily_swipe_count(address))


def consume_energy(address: str, card_type: str) -> dict:
    """Deduct energy. Returns {ok, remaining, cost}."""
    from app.config import get_settings
    s = get_settings()
    cost = s.energy_cost_premium if card_type in PREMIUM_CARD_TYPES else s.energy_cost_standard
    if get_energy(address) < cost:
        return {"ok": False, "remaining": get_energy(address), "cost": cost}
    conn = _get_conn()
    if not conn:
        return {"ok": True, "remaining": 0, "cost": cost}
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO daily_swipes (user_address, swipe_date, count)
               VALUES (%s, CURRENT_DATE, %s)
               ON CONFLICT (user_address, swipe_date)
               DO UPDATE SET count = daily_swipes.count + %s
               RETURNING count""",
            (address, cost, cost))
        new_count = cur.fetchone()[0]
    return {"ok": True, "remaining": max(0, s.energy_max - new_count), "cost": cost}


# ─── Energy refill ledger (tx-hash-keyed idempotency) ─────────────────


def get_refill(tx_hash: str) -> dict | None:
    """Look up a previously-redeemed refill by its on-chain tx hash."""
    if not tx_hash:
        return None
    conn = _get_conn()
    if not conn:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT tx_hash, user_address, session_id, amount_iusd, refilled_at "
            "FROM energy_refills WHERE tx_hash = %s",
            (tx_hash.lower(),))
        row = cur.fetchone()
    return dict(row) if row else None


def record_refill(tx_hash: str, user_address: str, session_id: int | None,
                  amount_iusd: str | None) -> bool:
    """Insert a refill row. Returns True if newly inserted, False if duplicate.

    `user_address` is stored verbatim (caller is expected to pass the checksum
    form from normalize_address — same form daily_swipes is keyed on)."""
    conn = _get_conn()
    if not conn:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO energy_refills (tx_hash, user_address, session_id, amount_iusd)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (tx_hash) DO NOTHING
               RETURNING tx_hash""",
            (tx_hash.lower(), user_address, session_id, amount_iusd))
        return cur.fetchone() is not None


def reset_daily_swipes(address: str) -> int:
    """Clear today's swipe count for an address. Returns rows deleted (0 or 1).

    Address is matched verbatim — must use the same form daily_swipes is
    keyed on (consume_energy stores the checksum address from normalize_address)."""
    if not address:
        return 0
    conn = _get_conn()
    if not conn:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM daily_swipes WHERE user_address = %s AND swipe_date = CURRENT_DATE",
            (address,))
        return cur.rowcount or 0


def get_recently_resolved_trades(address: str, since_hours: int = 24) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT * FROM trades WHERE user_address = %s AND resolved = TRUE
               AND created_at > NOW() - INTERVAL '24 hours'
               ORDER BY created_at DESC LIMIT 5""",
            (address,))
        return [dict(r) for r in cur.fetchall()]


# ─── Provider Signal Queries ─────────────────────────

def resolve_signal_with_type(signal_id: int, exit_price: str, resolution_type: str) -> bool:
    conn = _get_conn()
    if not conn:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signals SET exit_price = %s, resolved = TRUE, resolution_type = %s WHERE id = %s",
            (exit_price, resolution_type, signal_id))
        return cur.rowcount > 0


def get_unresolved_provider_signals() -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM signals WHERE resolved = FALSE AND provider != '' AND stop_loss != '0'")
        return [_row_to_signal(r) for r in cur.fetchall()]


def get_provider_stats(provider: str) -> dict:
    conn = _get_conn()
    if not conn:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "avg_return": 0, "current_streak": 0, "best_streak": 0,
                "active": 0, "expired": 0, "resolved": 0}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE resolved) as resolved,
                   COUNT(*) FILTER (WHERE resolution_type = 'TP_HIT') as wins,
                   COUNT(*) FILTER (WHERE resolution_type = 'SL_HIT') as losses,
                   COUNT(*) FILTER (WHERE resolution_type = 'EXPIRED') as expired,
                   COUNT(*) FILTER (WHERE NOT resolved) as active
            FROM signals WHERE provider = %s
        """, (provider,))
        row = cur.fetchone()
        if not row or row["total"] == 0:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                    "avg_return": 0, "current_streak": 0, "best_streak": 0,
                    "active": 0, "expired": 0, "resolved": 0}

        # Avg return
        cur.execute("""
            SELECT entry_price, exit_price, is_bull
            FROM signals WHERE provider = %s AND resolved = TRUE AND exit_price != '0'
        """, (provider,))
        resolved_rows = cur.fetchall()

    returns = []
    for r in resolved_rows:
        try:
            entry, exit_ = float(r["entry_price"]), float(r["exit_price"])
            if entry > 0:
                pct = (exit_ - entry) / entry * 100
                if not r["is_bull"]:
                    pct = -pct
                returns.append(pct)
        except (ValueError, ZeroDivisionError):
            pass
    avg_return = round(sum(returns) / len(returns), 2) if returns else 0

    # Streak from chronological resolved signals
    with _get_conn().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT resolution_type FROM signals
            WHERE provider = %s AND resolved = TRUE ORDER BY timestamp ASC
        """, (provider,))
        ordered = cur.fetchall()

    current_streak = best_streak = 0
    for s in ordered:
        if s["resolution_type"] == "TP_HIT":
            current_streak += 1
            best_streak = max(best_streak, current_streak)
        else:
            current_streak = 0

    resolved_count = row["resolved"]
    win_rate = round(row["wins"] / resolved_count * 100, 1) if resolved_count > 0 else 0
    return {
        "total": row["total"], "resolved": resolved_count, "active": row["active"],
        "wins": row["wins"], "losses": row["losses"], "expired": row["expired"],
        "win_rate": win_rate, "avg_return": avg_return,
        "current_streak": current_streak, "best_streak": best_streak,
    }


def get_provider_leaderboard(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT provider, COUNT(*) as total,
                   COUNT(*) FILTER (WHERE resolved) as resolved,
                   COUNT(*) FILTER (WHERE resolution_type = 'TP_HIT') as wins,
                   COUNT(*) FILTER (WHERE resolution_type = 'SL_HIT') as losses,
                   CASE WHEN COUNT(*) FILTER (WHERE resolved) > 0
                        THEN ROUND(COUNT(*) FILTER (WHERE resolution_type = 'TP_HIT')::numeric
                             / COUNT(*) FILTER (WHERE resolved) * 100, 1)
                        ELSE 0 END as win_rate
            FROM signals WHERE provider != ''
            GROUP BY provider HAVING COUNT(*) >= 5
            ORDER BY win_rate DESC LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]

# ─── User Agents ─────────────────────────────────────────────

def init_user_agents_table():
    conn = _get_conn()
    if not conn:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_agents (
                id SERIAL PRIMARY KEY,
                user_address TEXT NOT NULL UNIQUE,
                strategy TEXT DEFAULT 'balanced',
                max_position_usd DOUBLE PRECISION DEFAULT 50,
                tokens_whitelist JSONB DEFAULT '[]',
                tokens_blacklist JSONB DEFAULT '[]',
                min_confidence INTEGER DEFAULT 60,
                auto_execute BOOLEAN DEFAULT FALSE,
                risk_tolerance TEXT DEFAULT 'medium',
                take_profit_pct DOUBLE PRECISION DEFAULT 3.0,
                stop_loss_pct DOUBLE PRECISION DEFAULT 2.0,
                is_active BOOLEAN DEFAULT FALSE,
                learned_preferences JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_notifications (
                id SERIAL PRIMARY KEY,
                user_address TEXT NOT NULL,
                card_id INTEGER NOT NULL,
                message TEXT DEFAULT '',
                read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Add source column to trades if missing
        try:
            cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual'")
        except Exception:
            pass
    logger.info("user_agents table ready")
    # Reset timeout after init
    try:
        with conn.cursor() as cur:
            cur.execute("RESET statement_timeout")
    except Exception:
        pass


def upsert_user_agent(address: str, config: dict) -> dict:
    conn = _get_conn()
    if not conn:
        return {}
    fields = ["strategy", "max_position_usd", "tokens_whitelist", "tokens_blacklist",
              "min_confidence", "auto_execute", "risk_tolerance", "take_profit_pct", "stop_loss_pct", "is_active"]
    data = {k: config[k] for k in fields if k in config}
    if not data:
        return get_user_agent(address) or {}
    cols = ", ".join(data.keys())
    vals = ", ".join(["%s"] * len(data))
    updates = ", ".join(f"{k}=EXCLUDED.{k}" for k in data.keys())
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"INSERT INTO user_agents (user_address, {cols}, updated_at) VALUES (%s, {vals}, NOW()) "
            f"ON CONFLICT (user_address) DO UPDATE SET {updates}, updated_at=NOW() RETURNING *",
            [address] + [json.dumps(v) if isinstance(v, list) else v for v in data.values()])
        return dict(cur.fetchone())


def get_user_agent(address: str) -> dict | None:
    conn = _get_conn()
    if not conn:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM user_agents WHERE user_address=%s", (address,))
        row = cur.fetchone()
    return dict(row) if row else None


def get_active_user_agents() -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM user_agents WHERE is_active=TRUE")
        return [dict(r) for r in cur.fetchall()]


def get_recent_cards(minutes: int = 5) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM cards WHERE created_at > NOW() - INTERVAL '%s minutes' AND status='active'", (minutes,))
        return [dict(r) for r in cur.fetchall()]


def compute_preferences_from_swipes(address: str) -> dict:
    conn = _get_conn()
    if not conn:
        return {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT c.token_symbol, c.risk_score, c.verdict, s.action
            FROM swipes s JOIN cards c ON s.card_id = c.id
            WHERE s.user_address=%s ORDER BY s.created_at DESC LIMIT 100
        """, (address,))
        rows = cur.fetchall()
    if not rows:
        return {}
    apes = [r for r in rows if r["action"] == "ape"]
    if not apes:
        return {}
    preferred = list({r["token_symbol"] for r in apes})[:10]
    avg_risk = sum(r.get("risk_score") or 50 for r in apes) / len(apes)
    confidence_floor = max(30, 100 - round(avg_risk))
    return {"preferred_tokens": preferred, "avg_risk_score": round(avg_risk), "confidence_floor": confidence_floor}


def insert_agent_notification(address: str, card_id: int, message: str):
    conn = _get_conn()
    if not conn:
        return
    with conn.cursor() as cur:
        cur.execute("INSERT INTO agent_notifications (user_address, card_id, message) VALUES (%s,%s,%s)",
                    (address, card_id, message))


def get_agent_notifications(address: str, limit: int = 20) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM agent_notifications WHERE user_address=%s ORDER BY created_at DESC LIMIT %s",
                    (address, limit))
        return [dict(r) for r in cur.fetchall()]
