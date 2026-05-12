"""Agent Runner — matches new cards against user agent configs, executes or notifies."""
import logging
from app import db

logger = logging.getLogger(__name__)

_RISK_THRESHOLDS = {"low": 35, "medium": 60, "high": 100}


def run_user_agents():
    """Main loop: evaluate recent cards against all active user agents."""
    agents = db.get_active_user_agents()
    if not agents:
        return
    cards = db.get_recent_cards(minutes=5)
    if not cards:
        return

    matched = 0
    for agent in agents:
        for card in cards:
            if not _matches(card, agent):
                continue
            if agent["auto_execute"]:
                _execute(agent, card)
            else:
                _notify(agent, card)
            matched += 1

    if matched:
        logger.info(f"Agent runner: {matched} matches across {len(agents)} agents")


def _matches(card: dict, agent: dict) -> bool:
    """Does this card match the agent's preferences?"""
    # Only act on APE verdicts
    if card.get("verdict") != "APE":
        return False
    # Confidence filter
    confidence = card.get("confidence") or (100 - (card.get("risk_score") or 50))
    if confidence < agent["min_confidence"]:
        return False
    # Risk filter
    risk = card.get("risk_score") or 50
    if risk > _RISK_THRESHOLDS.get(agent["risk_tolerance"], 60):
        return False
    # Token whitelist
    symbol = card.get("token_symbol", "")
    whitelist = agent.get("tokens_whitelist") or []
    if whitelist and symbol not in whitelist:
        return False
    # Token blacklist
    blacklist = agent.get("tokens_blacklist") or []
    if symbol in blacklist:
        return False
    # Sentiment filter: low-risk agents skip negative sentiment tokens
    if agent["risk_tolerance"] == "low":
        sentiment = card.get("sentiment_score", 0)
        if sentiment < -20:
            return False
    return True


def _execute(agent: dict, card: dict):
    """Record an agent-initiated trade."""
    conn = db._get_conn()
    if not conn:
        return
    price = card.get("price", 0)
    if price <= 0:
        return
    amount_usd = agent["max_position_usd"]
    token_amount = amount_usd / price if price > 0 else 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trades (card_id, user_address, token_symbol, token_name, entry_price, amount_usd, token_amount, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'agent')",
                (card["id"], agent["user_address"], card["token_symbol"], card.get("token_name", ""),
                 price, amount_usd, round(token_amount, 8)))
        logger.info(f"Agent trade: {agent['user_address'][:10]}.. → {card['token_symbol']} @ ${price}")
    except Exception as e:
        logger.warning(f"Agent execute failed: {e}")


def _notify(agent: dict, card: dict):
    """Queue a notification for the user."""
    msg = f"🤖 {card['token_symbol']} signal ({card.get('confidence', '?')}% confidence) — {card.get('hook', '')}"
    db.insert_agent_notification(agent["user_address"], card["id"], msg)


def update_agent_preferences():
    """AutoResearch loop: re-learn preferences + self-correct confidence."""
    agents = db.get_active_user_agents()
    conn = db._get_conn()
    if not conn or not agents:
        return

    import json
    from psycopg2.extras import RealDictCursor

    for agent in agents:
        addr = agent["user_address"]
        # Re-compute learned preferences from swipes
        prefs = db.compute_preferences_from_swipes(addr)

        # Self-correction: check agent's recent win_rate
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END) as wins "
                "FROM trades WHERE user_address=%s AND source='agent' AND resolved=TRUE "
                "ORDER BY created_at DESC LIMIT 20", (addr,))
            row = cur.fetchone()

        total = row["total"] or 0
        wins = row["wins"] or 0
        new_confidence = agent["min_confidence"]

        if total >= 5:
            win_rate = wins / total
            if win_rate < 0.4:
                new_confidence = min(95, agent["min_confidence"] + 5)  # more conservative
            elif win_rate > 0.7:
                new_confidence = max(30, agent["min_confidence"] - 3)  # slightly more aggressive

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_agents SET learned_preferences=%s, min_confidence=%s, updated_at=NOW() WHERE user_address=%s",
                (json.dumps(prefs), new_confidence, addr))

    logger.info(f"AutoResearch: updated {len(agents)} agent preferences")
