"""Content Engine — 5-stage card generation pipeline.
Stage 1: Data Harvester (CoinGecko)
Stage 2: Signal Analyzer (pure logic)
Stage 3: Narrative Writer (Claude Bedrock + fallback)
Stage 4: Visual (token logo — image gen skipped for now)
Stage 5: Card Assembler (merge + store)
"""
import json
import logging
import random
import time
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

# ─── Stage 1: Data Harvester ────────────────────────────────

def harvest_tokens(limit: int = 10) -> list[dict]:
    """Fetch token data from CoinGecko markets API."""
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "volume_desc", "per_page": limit,
                    "page": 1, "sparkline": False, "price_change_percentage": "1h,24h"},
            timeout=15,
        )
        resp.raise_for_status()
        return [_parse_coingecko(c) for c in resp.json()]
    except Exception as e:
        logger.error(f"Harvest failed: {e}")
        return []


def _parse_coingecko(c: dict) -> dict:
    return {
        "coingecko_id": c["id"],
        "token_symbol": c["symbol"].upper(),
        "token_name": c["name"],
        "price": c.get("current_price", 0) or 0,
        "price_change_1h": c.get("price_change_percentage_1h_in_currency", 0) or 0,
        "price_change_24h": c.get("price_change_percentage_24h", 0) or 0,
        "volume_24h": c.get("total_volume", 0) or 0,
        "market_cap": c.get("market_cap", 0) or 0,
        "image_url": c.get("image", ""),
        "high_24h": c.get("high_24h", 0) or 0,
        "low_24h": c.get("low_24h", 0) or 0,
        "circulating_supply": c.get("circulating_supply", 0) or 0,
        "total_supply": c.get("total_supply", 0) or 0,
    }


# ─── Stage 2: Signal Analyzer (pure logic, no LLM) ─────────

def analyze_signals(token: dict) -> list[dict]:
    """Detect anomaly signals from raw token data. Returns sorted by severity."""
    signals = []
    pct_24h = token["price_change_24h"]
    pct_1h = token.get("price_change_1h", 0)
    vol = token["volume_24h"]
    mcap = token["market_cap"]

    # Volume spike: vol/mcap ratio
    if mcap > 0:
        vol_mcap = vol / mcap
        if vol_mcap > 0.5:
            signals.append({"type": "VOLUME_SPIKE", "severity": min(5, int(vol_mcap * 3)),
                            "direction": "bullish", "emoji": "🚨",
                            "finding": f"24h volume is {vol_mcap:.1f}x market cap"})

    # Price momentum
    if abs(pct_1h) > 5:
        d = "bullish" if pct_1h > 0 else "bearish"
        signals.append({"type": "PRICE_MOMENTUM", "severity": min(5, int(abs(pct_1h) / 3)),
                        "direction": d, "emoji": "🚀" if pct_1h > 0 else "📉",
                        "finding": f"Price moved {pct_1h:+.1f}% in 1 hour"})

    # 24h trend
    if abs(pct_24h) > 10:
        d = "bullish" if pct_24h > 0 else "bearish"
        signals.append({"type": "PRICE_MOMENTUM", "severity": min(5, int(abs(pct_24h) / 5)),
                        "direction": d, "emoji": "📊",
                        "finding": f"24h change: {pct_24h:+.1f}%"})

    # Buy pressure proxy: price near 24h high
    if token["high_24h"] > 0 and token["price"] > 0:
        pct_from_high = (token["price"] / token["high_24h"]) * 100
        if pct_from_high > 95:
            signals.append({"type": "BUY_SELL_IMBALANCE", "severity": 3,
                            "direction": "bullish", "emoji": "📈",
                            "finding": f"Trading at {pct_from_high:.0f}% of 24h high"})
        elif pct_from_high < 80:
            signals.append({"type": "BUY_SELL_IMBALANCE", "severity": 3,
                            "direction": "bearish", "emoji": "📉",
                            "finding": f"Trading at {pct_from_high:.0f}% of 24h high — weakness"})

    # Supply concentration proxy
    if token["circulating_supply"] > 0 and token["total_supply"] > 0:
        circ_pct = token["circulating_supply"] / token["total_supply"] * 100
        if circ_pct < 50:
            signals.append({"type": "HOLDER_CONCENTRATION", "severity": 4,
                            "direction": "bearish", "emoji": "🎯",
                            "finding": f"Only {circ_pct:.0f}% of supply circulating"})

    # Mcap to volume ratio (overheated)
    if mcap > 0 and vol > mcap * 2:
        signals.append({"type": "MCAP_TO_VOLUME_RATIO", "severity": 4,
                        "direction": "neutral", "emoji": "⚠️",
                        "finding": f"Volume ({_fmt(vol)}) exceeds 2x market cap ({_fmt(mcap)})"})

    return sorted(signals, key=lambda s: s["severity"], reverse=True)


def compute_risk_score(signals: list[dict]) -> int:
    """0-100. Higher = riskier."""
    base = 50
    for s in signals:
        if s["direction"] == "bearish":
            base += s["severity"] * 5
        elif s["direction"] == "bullish":
            base -= s["severity"] * 3
    return max(0, min(100, base))


def compute_verdict(signals: list[dict], risk_score: int) -> tuple[str, str, str]:
    """Returns (verdict, verdict_reason, risk_level)."""
    bull = sum(s["severity"] for s in signals if s["direction"] == "bullish")
    bear = sum(s["severity"] for s in signals if s["direction"] == "bearish")

    if risk_score >= 70:
        risk_level = "DEGEN"
    elif risk_score <= 35:
        risk_level = "SAFE"
    else:
        risk_level = "MID"

    if bull > bear + 3:
        verdict = "APE"
        reason = f"Bullish signals ({bull}) outweigh bearish ({bear}). Momentum is real."
    elif bear > bull + 3:
        verdict = "FADE"
        reason = f"Bearish signals ({bear}) dominate. Risk score {risk_score}/100."
    else:
        verdict = "DYOR"
        reason = f"Mixed signals. Bull={bull}, Bear={bear}. Proceed with caution."

    return verdict, reason, risk_level


# ─── Stage 3: Narrative Writer ──────────────────────────────

def generate_narrative(token: dict, signals: list[dict], risk_score: int) -> dict:
    """Try Claude Bedrock, fall back to templates."""
    verdict, verdict_reason, risk_level = compute_verdict(signals, risk_score)
    content = _narrative_via_bedrock(token, signals, verdict, risk_level)
    if not content:
        content = _narrative_fallback(token, signals, verdict, risk_level)
    content["verdict"] = verdict
    content["verdict_reason"] = verdict_reason
    content["risk_level"] = risk_level
    content["risk_score"] = risk_score
    return content


def _narrative_via_bedrock(token: dict, signals: list[dict], verdict: str, risk_level: str) -> dict | None:
    settings = get_settings()
    signal_lines = "\n".join(f"- [{s['severity']}/5 {s['direction']}] {s['finding']}" for s in signals[:5])
    prompt = (
        f'You are the AI of "Ape or Fade" — savage, sarcastic, brilliant crypto analyst. '
        f'Gen-Z tone. Never boring. Take a stance.\n\n'
        f'Token: {token["token_name"]} (${token["token_symbol"]})\n'
        f'Price: ${token["price"]:,.6f}, 1h: {token.get("price_change_1h",0):+.1f}%, '
        f'24h: {token["price_change_24h"]:+.1f}%\n'
        f'Vol: ${token["volume_24h"]:,.0f}, MCap: ${token["market_cap"]:,.0f}\n'
        f'Verdict: {verdict}, Risk: {risk_level}\n'
        f'Signals:\n{signal_lines}\n\n'
        f'Respond ONLY with JSON:\n'
        f'{{"hook":"punchy scroll-stopper max 12 words",'
        f'"roast":"1-2 sarcastic sentences with data insights",'
        f'"metrics":[{{"emoji":"X","label":"Y","value":"Z","sentiment":"bullish|bearish|neutral"}},'
        f'{{"emoji":"X","label":"Y","value":"Z","sentiment":"bullish|bearish|neutral"}},'
        f'{{"emoji":"X","label":"Y","value":"Z","sentiment":"bullish|bearish|neutral"}}],'
        f'"notification_hook":"what to message if they faded and it pumped, max 15 words",'
        f'"ai_image_prompt":"surreal meme scene for this token vibe"}}'
    )
    try:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
        resp = client.invoke_model(
            modelId=settings.aws_bedrock_model_id,
            contentType="application/json", accept="application/json",
            body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 400,
                             "messages": [{"role": "user", "content": prompt}]}),
        )
        text = json.loads(resp["body"].read())["content"][0]["text"]
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        logger.warning(f"Bedrock unavailable for {token['token_symbol']}: {e}")
    return None


def _narrative_fallback(token: dict, signals: list[dict], verdict: str, risk_level: str) -> dict:
    """Template-based narrative when LLM unavailable."""
    sym = token["token_symbol"]
    pct = token["price_change_24h"]

    hooks = {
        "APE": [f"${sym} is cooking. The numbers don't lie.", f"${sym} woke up and chose violence.",
                f"Everyone sleeping on ${sym}. Not anymore."],
        "FADE": [f"${sym} is a dumpster fire right now.", f"${sym} holders in shambles.",
                 f"RIP to everyone who aped ${sym}."],
        "DYOR": [f"${sym} is giving mixed signals.", f"${sym} can't decide what it wants to be.",
                 f"${sym} is the definition of 'it's complicated'."],
    }
    hook = random.choice(hooks.get(verdict, hooks["DYOR"]))

    top_signals = signals[:3] if signals else []
    signal_text = ". ".join(s["finding"] for s in top_signals) if top_signals else f"{pct:+.1f}% in 24h"
    roast = f"{signal_text}. {'Degen energy is real.' if verdict == 'APE' else 'Proceed with extreme caution.' if verdict == 'FADE' else 'Make your own call.'}"

    metrics = [{"emoji": s["emoji"], "label": s["type"].replace("_", " ").title(),
                "value": s["finding"].split(":")[- 1].strip() if ":" in s["finding"] else s["finding"],
                "sentiment": s["direction"]} for s in top_signals]
    while len(metrics) < 3:
        metrics.append({"emoji": "📊", "label": "24h Change", "value": f"{pct:+.1f}%",
                        "sentiment": "bullish" if pct > 0 else "bearish"})

    notification = f"You faded ${sym}. It's up big. Enjoy watching from the sidelines."

    return {"hook": hook, "roast": roast, "metrics": metrics[:3],
            "notification_hook": notification,
            "ai_image_prompt": f"{sym} crypto {'rocket launch' if verdict == 'APE' else 'crash landing' if verdict == 'FADE' else 'foggy crossroads'}"}


# ─── Stage 5: Card Assembler ────────────────────────────────

def assemble_card(token: dict, signals: list[dict], narrative: dict) -> dict:
    """Merge all pipeline outputs into final card object."""
    return {
        **token,
        "hook": narrative["hook"],
        "roast": narrative["roast"],
        "metrics": narrative["metrics"],
        "verdict": narrative["verdict"],
        "verdict_reason": narrative["verdict_reason"],
        "risk_level": narrative["risk_level"],
        "risk_score": narrative["risk_score"],
        "notification_hook": narrative.get("notification_hook", ""),
        "ai_image_prompt": narrative.get("ai_image_prompt", ""),
        "signals": [{"type": s["type"], "severity": s["severity"],
                     "direction": s["direction"], "finding": s["finding"]}
                    for s in signals[:5]],
    }


# ─── Pipeline Orchestrator ──────────────────────────────────

def run_card_generation_cycle():
    """Master pipeline: harvest → analyze → narrate → assemble → store."""
    from app.db import insert_card, get_existing_coingecko_ids

    logger.info("Running card generation pipeline...")
    t0 = time.time()

    # Stage 1: Harvest
    tokens = harvest_tokens(15)
    if not tokens:
        logger.warning("No tokens harvested")
        return

    # Filter already-carded
    existing = get_existing_coingecko_ids()
    new_tokens = [t for t in tokens if t["coingecko_id"] not in existing]
    if not new_tokens:
        logger.info("All tokens already carded")
        return

    created = 0
    for token in new_tokens[:5]:
        try:
            # Stage 2: Analyze signals
            signals = analyze_signals(token)
            risk_score = compute_risk_score(signals)

            # Skip boring tokens (no notable signals)
            if signals and max(s["severity"] for s in signals) < 2:
                continue

            # Stage 3: Narrative
            narrative = generate_narrative(token, signals, risk_score)

            # Stage 4: Visual (using CoinGecko logo for now)
            # Stage 5: Assemble
            card = assemble_card(token, signals, narrative)
            card_id = insert_card(card)
            if card_id > 0:
                created += 1
                logger.info(f"Card #{card_id}: ${token['token_symbol']} [{narrative['verdict']}] "
                            f"risk={risk_score} — {narrative['hook']}")
        except Exception as e:
            logger.error(f"Pipeline failed for {token['token_symbol']}: {e}")

    elapsed = time.time() - t0
    logger.info(f"Pipeline complete: {created} cards in {elapsed:.1f}s from {len(new_tokens)} candidates")


def _fmt(v: float) -> str:
    if v >= 1e9: return f"${v/1e9:.1f}B"
    if v >= 1e6: return f"${v/1e6:.0f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"
