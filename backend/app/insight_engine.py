"""Module B: Insight Engine — generates non-tradeable insight cards from SoSoValue data."""
import logging
from datetime import datetime, timezone, timedelta
from app.sosovalue_client import get_full_context
from app import db

log = logging.getLogger(__name__)

_MAX_CARDS = 3


def generate_insight_cards() -> list[dict]:
    """Generate insight cards from SoSoValue data. Max 3 per cycle."""
    ctx = get_full_context()
    if not ctx:
        return []
    cards = []
    for gen in (_etf_flow_card, _macro_alert_card, _index_movers_card, _btc_treasury_card, _hot_news_card):
        if len(cards) >= _MAX_CARDS:
            break
        card = gen(ctx)
        if card:
            cards.append(card)
    return cards


def generate_and_store_insight_cards():
    """Generate insight cards and persist to DB."""
    cards = generate_insight_cards()
    for card in cards:
        try:
            db.insert_card(card)
        except Exception as e:
            log.warning("Failed to insert insight card: %s", e)
    if cards:
        log.info("Stored %d insight cards", len(cards))


def _make_card(name: str, hook: str, roast: str, metrics: list) -> dict:
    return {
        "token_symbol": "INSIGHT",
        "token_name": name,
        "card_type": "insight",
        "hook": hook,
        "roast": roast,
        "metrics": metrics,
        "price": 0, "price_change_24h": 0, "volume_24h": 0, "market_cap": 0,
        "status": "active",
        "source": "sosovalue",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
    }


def _etf_flow_card(ctx: dict) -> dict | None:
    flows = ctx.get("etf_flows", {})
    btc_flow = flows.get("btc_net_flow", 0)
    if abs(btc_flow) < 50_000_000:
        return None
    direction = "absorbed" if btc_flow > 0 else "dumped"
    amt = f"${abs(btc_flow) / 1e6:.0f}M"
    hook = f"🏦 BTC ETFs just {direction} {amt}"
    roast = "Institutions loading up while CT argues about memes." if btc_flow > 0 else "Suits are exiting. Maybe they know something you don't."
    return _make_card("ETF Flow Update", hook, roast, [{"emoji": "🏦", "label": "BTC ETF", "value": f"{'+' if btc_flow > 0 else ''}{amt}"}])


def _macro_alert_card(ctx: dict) -> dict | None:
    events = ctx.get("macro_events", [])
    if not events:
        return None
    evt = events[0]
    name = evt.get("name", "Unknown event")
    hook = f"📊 Macro Alert: {name}"
    roast = "Set your stops or touch grass until it's over."
    return _make_card("Macro Alert", hook, roast, [{"emoji": "📊", "label": "Event", "value": name[:30]}])


def _index_movers_card(ctx: dict) -> dict | None:
    indices = ctx.get("indices", [])
    if not indices:
        return None
    # Pick first index with data
    for idx in indices[:3]:
        ticker = idx if isinstance(idx, str) else idx.get("ticker", "")
        if ticker:
            hook = f"📈 SSI Index Update: {ticker.upper()}"
            roast = "Baskets move while you pick single coins. Diversification is not a meme."
            return _make_card("Index Movers", hook, roast, [{"emoji": "📈", "label": "Index", "value": ticker.upper()}])
    return None


def _btc_treasury_card(ctx: dict) -> dict | None:
    treasuries = ctx.get("btc_treasuries", [])
    if not treasuries:
        return None
    top = treasuries[0]
    company = top.get("company", top.get("name", "Unknown"))
    btc = top.get("btc_held", top.get("btcHeld", top.get("total", "?")))
    hook = f"🏛️ {company} holds {btc} BTC"
    roast = "Corporate treasuries are stacking. Your 0.01 BTC is cute though."
    return _make_card("BTC Treasury", hook, roast, [{"emoji": "🏛️", "label": company[:20], "value": f"{btc} BTC"}])


def _hot_news_card(ctx: dict) -> dict | None:
    news = ctx.get("featured_news") or ctx.get("hot_news", [])
    if not news:
        return None
    item = news[0]
    title = item.get("title", "")[:80]
    if not title:
        return None
    hook = f"🔥 {title}"
    roast = "Breaking news that'll be forgotten by tomorrow. Trade accordingly."
    return _make_card("Hot News", hook, roast, [{"emoji": "🔥", "label": "News", "value": title[:30]}])
