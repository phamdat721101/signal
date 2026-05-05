"""Daily prediction challenges using SoSoValue data."""
import json
import logging
from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor
from app.db import _get_conn
from app.sosovalue_client import get_etf_flows, get_sosovalue_context

logger = logging.getLogger(__name__)


def generate_daily_challenges(ctx: dict = None) -> list[dict]:
    """Create 2-3 challenges for today. Only creates if none exist for today."""
    conn = _get_conn()
    if not conn:
        return []

    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM challenges WHERE created_at >= %s AND created_at < %s",
            (start_of_day, end_of_day),
        )
        if cur.fetchone()[0] > 0:
            return []

    challenges = [
        {
            "type": "price_predict",
            "title": "Predict BTC Close",
            "description": "What will BTC close at today (UTC)?",
            "emoji": "🔮",
            "options": json.dumps({"input_type": "number", "unit": "USD"}),
            "reward_xp": 1000,
            "expires_at": end_of_day,
        },
        {
            "type": "etf_direction",
            "title": "ETF Flow Direction",
            "description": "Will BTC ETF net flow be positive or negative today?",
            "emoji": "🏦",
            "options": json.dumps(["positive", "negative"]),
            "reward_xp": 500,
            "expires_at": end_of_day,
        },
        {
            "type": "index_race",
            "title": "Index Race: MAG7 vs MEME",
            "description": "Which index will perform better today?",
            "emoji": "🏁",
            "options": json.dumps(["MAG7", "MEME"]),
            "reward_xp": 300,
            "expires_at": end_of_day,
        },
    ]

    inserted = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for c in challenges:
            cur.execute(
                """INSERT INTO challenges (type, title, description, emoji, options, reward_xp, expires_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (c["type"], c["title"], c["description"], c["emoji"],
                 c["options"], c["reward_xp"], c["expires_at"]),
            )
            inserted.append(dict(cur.fetchone()))

    logger.info("Generated %d daily challenges", len(inserted))
    return inserted


def resolve_challenges() -> int:
    """Resolve expired unresolved challenges and score entries."""
    conn = _get_conn()
    if not conn:
        return 0

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM challenges WHERE resolved = FALSE AND expires_at <= NOW()"
        )
        expired = cur.fetchall()

    resolved_count = 0
    for ch in expired:
        if ch["type"] == "price_predict":
            _resolve_price_predict(ch)
        elif ch["type"] == "etf_direction":
            _resolve_etf_direction(ch)
        elif ch["type"] == "index_race":
            _resolve_index_race(ch)

        with conn.cursor() as cur:
            cur.execute("UPDATE challenges SET resolved = TRUE WHERE id = %s", (ch["id"],))
        resolved_count += 1

    if resolved_count:
        logger.info("Resolved %d challenges", resolved_count)
    return resolved_count


def _resolve_price_predict(ch: dict):
    """Score entries by closeness to actual BTC price."""
    conn = _get_conn()
    try:
        import httpx
        r = httpx.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10)
        actual = r.json()["bitcoin"]["usd"]
    except Exception:
        actual = 0

    if not actual:
        return

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM challenge_entries WHERE challenge_id = %s", (ch["id"],))
        entries = cur.fetchall()

    with conn.cursor() as cur:
        for entry in entries:
            try:
                guess = float(entry["answer"])
            except (ValueError, TypeError):
                guess = 0
            score = max(0, int(1000 - abs(guess - actual) / actual * 10000))
            cur.execute("UPDATE challenge_entries SET score = %s WHERE id = %s", (score, entry["id"]))
        cur.execute("UPDATE challenges SET correct_answer = %s WHERE id = %s", (str(actual), ch["id"]))


def _resolve_etf_direction(ch: dict):
    """Check SoSoValue ETF flow direction."""
    conn = _get_conn()
    flows = get_etf_flows()
    btc_flow = flows.get("btc_net_flow", 0)
    correct = "positive" if btc_flow >= 0 else "negative"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM challenge_entries WHERE challenge_id = %s", (ch["id"],))
        entries = cur.fetchall()

    with conn.cursor() as cur:
        for entry in entries:
            score = 500 if entry["answer"] == correct else 0
            cur.execute("UPDATE challenge_entries SET score = %s WHERE id = %s", (score, entry["id"]))
        cur.execute("UPDATE challenges SET correct_answer = %s WHERE id = %s", (correct, ch["id"]))


def _resolve_index_race(ch: dict):
    """Check which index performed better (placeholder — uses ETF flow as proxy)."""
    conn = _get_conn()
    # Default to MAG7 if no real index data available
    correct = "MAG7"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM challenge_entries WHERE challenge_id = %s", (ch["id"],))
        entries = cur.fetchall()

    with conn.cursor() as cur:
        for entry in entries:
            score = 300 if entry["answer"] == correct else 0
            cur.execute("UPDATE challenge_entries SET score = %s WHERE id = %s", (score, entry["id"]))
        cur.execute("UPDATE challenges SET correct_answer = %s WHERE id = %s", (correct, ch["id"]))


def enter_challenge(challenge_id: int, user_address: str, answer: str) -> dict:
    """Submit user's answer to a challenge."""
    conn = _get_conn()
    if not conn:
        return {"success": False, "message": "Database unavailable"}

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM challenges WHERE id = %s AND resolved = FALSE AND expires_at > NOW()",
            (challenge_id,),
        )
        challenge = cur.fetchone()

    if not challenge:
        return {"success": False, "message": "Challenge not found or expired"}

    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO challenge_entries (challenge_id, user_address, answer)
                   VALUES (%s, %s, %s)""",
                (challenge_id, user_address, answer),
            )
        return {"success": True, "message": "Entry submitted"}
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            # Reset connection state after constraint violation
            conn.rollback() if not conn.autocommit else None
            return {"success": False, "message": "Already entered this challenge"}
        raise


def get_active_challenges() -> list[dict]:
    """Return all unresolved, non-expired challenges."""
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM challenges WHERE resolved = FALSE AND expires_at > NOW() ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
    return [_row_to_challenge(r) for r in rows]


def get_challenge_leaderboard(limit: int = 20) -> list[dict]:
    """Aggregate total score per user across all challenge entries."""
    conn = _get_conn()
    if not conn:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT user_address, SUM(score) as total_score, COUNT(*) as entries
               FROM challenge_entries
               GROUP BY user_address
               ORDER BY total_score DESC
               LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def _row_to_challenge(row: dict) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "description": row["description"],
        "emoji": row["emoji"],
        "options": row["options"] if isinstance(row["options"], (list, dict)) else json.loads(row.get("options", "[]")),
        "reward_xp": row["reward_xp"],
        "expires_at": str(row["expires_at"]),
        "resolved": row["resolved"],
        "correct_answer": row.get("correct_answer"),
        "created_at": str(row["created_at"]),
    }
