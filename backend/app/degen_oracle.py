"""Module C: Degen Oracle — market mood + hot takes via pure math + templates."""
import logging, random, time
from app.sosovalue_client import get_full_context
from app import db

log = logging.getLogger(__name__)

_oracle_state: dict = {}
_recent_takes: list[dict] = []

TAKE_TEMPLATES = {
    "etf_inflow": [
        "Suits buying {amount} of BTC while you're still DCA-ing $50/week. ngmi. 🏦",
        "BlackRock just ate {amount} of BTC for breakfast. You're not bullish enough. 🐂",
    ],
    "etf_outflow": [
        "Institutions dumped {amount} of BTC. They have info you don't. 🚨",
        "{amount} just left BTC ETFs. Somebody's scared. Are you? 🐻",
    ],
    "macro_event": [
        "Macro event incoming: {event}. Set your stops or get rekt. ⚠️",
        "{event} drops soon. The Oracle suggests touching grass until then. 📊",
    ],
    "crab": [
        "Market's going sideways. Perfect time to overthink your next trade. 🦀",
        "Nothing's moving. The calm before the storm or just... calm. 🦀",
    ],
}


def generate_oracle_mood(ctx: dict) -> dict:
    """Determine market mood from ETF flows + price data."""
    flows = ctx.get("etf_flows", {})
    btc_flow = flows.get("btc_net_flow", 0)
    flow_m = btc_flow / 1e6

    if flow_m > 200:
        return {"mood": "euphoric", "emoji": "🚀", "take": "Everything is pumping and nothing makes sense. Peak degen hours."}
    if flow_m > 100:
        return {"mood": "bullish", "emoji": "🐂", "take": "Institutions are buying. Maybe you should too. NFA."}
    if flow_m < -100:
        return {"mood": "bearish", "emoji": "🐻", "take": "Money's leaving. The Oracle sees red candles in your future."}
    if flow_m < -200:
        return {"mood": "apocalyptic", "emoji": "💀", "take": "Massive outflows. This is fine. Everything is fine. 🔥"}
    return {"mood": "crab", "emoji": "🦀", "take": "Sideways action. The market is as indecisive as you are."}


def generate_oracle_hot_takes(ctx: dict) -> list[dict]:
    """Generate hot takes from current market context."""
    takes = []
    flows = ctx.get("etf_flows", {})
    btc_flow = flows.get("btc_net_flow", 0)
    amt = f"${abs(btc_flow) / 1e6:.0f}M"

    if btc_flow > 50_000_000:
        takes.append({"take": random.choice(TAKE_TEMPLATES["etf_inflow"]).format(amount=amt), "emoji": "🏦"})
    elif btc_flow < -50_000_000:
        takes.append({"take": random.choice(TAKE_TEMPLATES["etf_outflow"]).format(amount=amt), "emoji": "🚨"})

    events = ctx.get("macro_events", [])
    if events:
        name = events[0].get("name", "Unknown")
        takes.append({"take": random.choice(TAKE_TEMPLATES["macro_event"]).format(event=name), "emoji": "📊"})

    if not takes:
        takes.append({"take": random.choice(TAKE_TEMPLATES["crab"]), "emoji": "🦀"})

    return takes


def refresh_oracle():
    """Called by scheduler. Updates in-memory state and persists takes."""
    global _oracle_state, _recent_takes
    ctx = get_full_context()
    if not ctx:
        return
    mood = generate_oracle_mood(ctx)
    takes = generate_oracle_hot_takes(ctx)
    _oracle_state = {**mood, "updated_at": int(time.time())}
    _recent_takes = takes + _recent_takes
    _recent_takes = _recent_takes[:20]  # keep last 20

    # Persist to DB
    conn = db._get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                for t in takes:
                    cur.execute(
                        "INSERT INTO oracle_takes (mood, take, emoji) VALUES (%s, %s, %s)",
                        (mood["mood"], t["take"], t["emoji"]))
        except Exception as e:
            log.warning("Failed to persist oracle takes: %s", e)


def get_current_mood() -> dict:
    """Return current oracle state."""
    if not _oracle_state:
        return {"mood": "sleeping", "emoji": "😴", "take": "The Oracle hasn't woken up yet. Check back soon."}
    return _oracle_state


def get_recent_takes(limit: int = 5) -> list:
    """Return recent hot takes from memory."""
    return _recent_takes[:limit]
