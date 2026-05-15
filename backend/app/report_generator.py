"""Premium report generator — assembles market data into structured reports."""
import logging
import time

logger = logging.getLogger(__name__)


async def generate_premium_report(report_type: str) -> dict:
    """Generate a premium report using existing data sources. No threads."""
    if report_type == "market_overview":
        return await _market_overview()
    elif report_type == "token_deep_dive":
        return await _token_deep_dive()
    elif report_type == "portfolio_advisory":
        return await _portfolio_advisory()
    return await _market_overview()


async def _market_overview() -> dict:
    """Full market analysis using existing engines."""
    from app.sosovalue_client import get_full_context
    from app.sentiment_engine import compute_sentiment
    from app.db import get_cards

    sv = get_full_context()
    btc_sent = compute_sentiment("BTC")
    eth_sent = compute_sentiment("ETH")

    # Top signals from recent cards
    cards, _ = get_cards(0, 5)
    top_signals = []
    for c in cards:
        if c.get("verdict") in ("APE", "FADE"):
            entry = c.get("price", 0)
            top_signals.append({
                "token": c["token_symbol"],
                "direction": c["verdict"],
                "confidence": max(10, 100 - (c.get("risk_score") or 50)),
                "entry": round(entry, 2),
                "target": round(entry * (1.015 if c["verdict"] == "APE" else 0.985), 2),
                "stop": round(entry * (0.985 if c["verdict"] == "APE" else 1.015), 2),
                "reasoning": c.get("verdict_reason", ""),
            })

    etf = sv.get("etf_flows", {})
    macro = sv.get("macro_events", [])

    return {
        "type": "market_overview",
        "generated_at": time.time(),
        "market_summary": {
            "btc_sentiment": btc_sent.get("score", 0),
            "btc_direction": btc_sent.get("direction", "neutral"),
            "eth_sentiment": eth_sent.get("score", 0),
            "eth_direction": eth_sent.get("direction", "neutral"),
        },
        "etf_flows": {
            "btc_net_flow": etf.get("btc_net_flow", 0),
            "eth_net_flow": etf.get("eth_net_flow", 0),
        },
        "macro_events": [e.get("name", "") for e in macro[:3]] if macro else [],
        "top_signals": top_signals[:5],
        "risk_level": "medium" if abs(btc_sent.get("score", 0)) < 50 else "high",
    }


async def _token_deep_dive() -> dict:
    """Deep dive on top-performing token."""
    from app.db import get_cards
    from app.sentiment_engine import compute_sentiment

    cards, _ = get_cards(0, 1)
    if not cards:
        return {"type": "token_deep_dive", "error": "No tokens available"}

    card = cards[0]
    sym = card["token_symbol"]
    sent = compute_sentiment(sym)

    return {
        "type": "token_deep_dive",
        "generated_at": time.time(),
        "token": sym,
        "price": card.get("price", 0),
        "sentiment": sent,
        "verdict": card.get("verdict", "DYOR"),
        "confidence": max(10, 100 - (card.get("risk_score") or 50)),
        "analysis": card.get("verdict_reason", ""),
        "debate_summary": card.get("debate_summary", ""),
        "trade_plan": card.get("trade_plan", {}),
    }


async def _portfolio_advisory() -> dict:
    """Portfolio allocation recommendation."""
    from app.sentiment_engine import compute_sentiment
    from app.db import get_cards

    btc = compute_sentiment("BTC")
    eth = compute_sentiment("ETH")

    # Dynamic allocation based on sentiment
    btc_score = btc.get("score", 0)
    eth_score = eth.get("score", 0)
    risk_off = btc_score < -20 or eth_score < -20

    allocation = {
        "BTC": 30 if risk_off else 40,
        "ETH": 20 if risk_off else 30,
        "ALT": 10 if risk_off else 20,
        "USDC": 40 if risk_off else 10,
    }

    return {
        "type": "portfolio_advisory",
        "generated_at": time.time(),
        "allocation": allocation,
        "risk_level": "high" if risk_off else "medium",
        "action": "Reduce exposure, hold stables" if risk_off else "Increase exposure on dips",
        "btc_outlook": btc.get("direction", "neutral"),
        "eth_outlook": eth.get("direction", "neutral"),
    }
