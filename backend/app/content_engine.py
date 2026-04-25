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




def generate_card_svg(card: dict) -> str:
    """Generate an SVG card image from card metadata."""
    sym = card.get('token_symbol', '??')
    verdict = card.get('verdict', 'DYOR')
    risk_level = card.get('risk_level', 'MID')
    pct = card.get('price_change_24h', 0)
    risk_score = card.get('risk_score', 50)

    # Colors by verdict
    colors = {'APE': ('#8eff71', '#0b5800'), 'FADE': ('#ff7166', '#5c0800'), 'DYOR': ('#bf81ff', '#3a0066')}
    accent, accent_dark = colors.get(verdict, colors['DYOR'])

    # Risk bar width (0-100 mapped to 0-260)
    bar_w = max(10, min(260, int(risk_score * 2.6)))

    # Price display
    price = card.get('price', 0)
    price_str = f'$' + f'{price:,.2f}' if price >= 1 else f'$' + f'{price:.6f}'
    pct_str = f'{pct:+.1f}%'
    pct_color = '#8eff71' if pct >= 0 else '#ff7166'

    # Metrics (up to 3)
    metrics = card.get('metrics', [])
    metric_rows = ''
    for i, m in enumerate(metrics[:3]):
        if isinstance(m, dict):
            label = m.get('label', '')[:18]
            value = m.get('value', '')[:20]
            emoji = m.get('emoji', '')
        else:
            label, value, emoji = str(m)[:18], '', ''
        y = 248 + i * 28
        metric_rows += f'<text x="30" y="{y}" fill="#adaaaa" font-size="11" font-family="monospace">{_svg_escape(label)}</text>'
        metric_rows += f'<text x="370" y="{y}" fill="#fff" font-size="11" font-family="monospace" text-anchor="end">{value}</text>'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 340" width="400" height="340">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#131313"/>
      <stop offset="100%" stop-color="#1a1919"/>
    </linearGradient>
    <linearGradient id="ac" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{accent}"/>
      <stop offset="100%" stop-color="{accent}88"/>
    </linearGradient>
  </defs>
  <rect width="400" height="340" rx="16" fill="url(#bg)"/>
  <rect x="0" y="0" width="400" height="4" rx="2" fill="{accent}"/>
  <text x="30" y="50" fill="{accent}" font-size="36" font-weight="900" font-family="system-ui,sans-serif">${sym}</text>
  <rect x="30" y="62" width="60" height="22" rx="4" fill="{accent_dark}"/>
  <text x="60" y="78" fill="{accent}" font-size="11" font-weight="700" font-family="monospace" text-anchor="middle">{verdict}</text>
  <text x="370" y="42" fill="#fff" font-size="18" font-weight="700" font-family="monospace" text-anchor="end">{price_str}</text>
  <text x="370" y="62" fill="{pct_color}" font-size="14" font-family="monospace" text-anchor="end">{pct_str}</text>
  <line x1="30" y1="100" x2="370" y2="100" stroke="#262626" stroke-width="1"/>
  <text x="30" y="125" fill="#adaaaa" font-size="10" font-family="monospace" text-transform="uppercase">RISK SCORE</text>
  <rect x="30" y="133" width="260" height="6" rx="3" fill="#262626"/>
  <rect x="30" y="133" width="{bar_w}" height="6" rx="3" fill="url(#ac)"/>
  <text x="300" y="141" fill="#adaaaa" font-size="10" font-family="monospace">{risk_score}/100</text>
  <text x="370" y="125" fill="#494847" font-size="10" font-family="monospace" text-anchor="end">{risk_level}</text>
  <line x1="30" y1="160" x2="370" y2="160" stroke="#262626" stroke-width="1"/>
  <text x="30" y="185" fill="#fff" font-size="13" font-weight="600" font-family="system-ui,sans-serif">{_svg_escape(card.get('hook', '')[:60])}</text>
  <text x="30" y="210" fill="#494847" font-size="11" font-family="system-ui,sans-serif">{_svg_escape(card.get('roast', '')[:80])}</text>
  <line x1="30" y1="230" x2="370" y2="230" stroke="#262626" stroke-width="1"/>
  {metric_rows}
  <text x="200" y="332" fill="#262626" font-size="9" font-family="monospace" text-anchor="middle">KINETIC | APE OR FADE</text>
</svg>"""


def _svg_escape(s: str) -> str:
    import re
    s = re.sub(r'[^ -~]', '', s)  # ASCII printable only (strips emojis)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


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


# --- Stage 2.5: Chart Analyzer -------------------------------------------

def fetch_chart_data(coingecko_id: str) -> list[float]:
    try:
        resp = httpx.get(
            f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/market_chart",
            params={"vs_currency": "usd", "days": 1}, timeout=15,
        )
        resp.raise_for_status()
        return [p[1] for p in resp.json().get("prices", [])]
    except Exception as e:
        logger.warning(f"Chart fetch failed for {coingecko_id}: {e}")
        return []


def _ema(prices: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    ema = [prices[0]]
    for p in prices[1:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema


def _build_sparkline(prices: list[float], points: int = 48) -> list[float]:
    if len(prices) < 2:
        return []
    step = max(1, len(prices) // points)
    return [round(prices[i], 2) for i in range(0, len(prices), step)][:points]


PATTERN_LESSONS = {
    "EMA_CROSSOVER": "EMA crossovers signal trend reversals — historically leading to 2-5% moves within 24h.",
    "BREAKOUT": "Breakouts above 24h highs often trigger momentum buying as stop-losses get hit.",
    "HIGHER_HIGHS": "Consecutive higher peaks confirm an uptrend — each dip is a buying opportunity.",
    "LOWER_HIGHS": "Consecutive lower peaks signal a downtrend — rallies are selling opportunities.",
    "CONSOLIDATION": "Tight price ranges build energy — the breakout direction usually continues.",
    "SUPPORT_TEST": "Price bouncing off the same level creates a floor that buyers defend.",
}


def detect_patterns(prices: list[float]) -> list[dict]:
    if len(prices) < 20:
        return []
    patterns = []
    ema5 = _ema(prices, 5)
    ema20 = _ema(prices, 20)
    for i in range(-min(48, len(ema5) - 1), 0):
        if ema5[i - 1] <= ema20[i - 1] and ema5[i] > ema20[i]:
            patterns.append({"type": "EMA_CROSSOVER", "direction": "bullish",
                             "label": "EMA Crossover ↑", "description": "Short-term trend crossed above long-term"})
            break
        elif ema5[i - 1] >= ema20[i - 1] and ema5[i] < ema20[i]:
            patterns.append({"type": "EMA_CROSSOVER", "direction": "bearish",
                             "label": "EMA Crossover ↓", "description": "Short-term trend crossed below long-term"})
            break
    high_24h, low_24h = max(prices), min(prices)
    recent = prices[-12:] if len(prices) >= 12 else prices
    if max(recent) >= high_24h * 0.999:
        patterns.append({"type": "BREAKOUT", "direction": "bullish",
                         "label": "24h Breakout ↑", "description": "Price breaking above 24-hour high"})
    elif min(recent) <= low_24h * 1.001:
        patterns.append({"type": "BREAKOUT", "direction": "bearish",
                         "label": "24h Breakdown ↓", "description": "Price breaking below 24-hour low"})
    if len(prices) >= 60:
        thirds = [prices[i:i + len(prices) // 3] for i in range(0, len(prices), len(prices) // 3)][:3]
        if len(thirds) == 3:
            highs = [max(t) for t in thirds]
            if highs[0] < highs[1] < highs[2]:
                patterns.append({"type": "HIGHER_HIGHS", "direction": "bullish",
                                 "label": "Higher Highs", "description": "Consecutive higher peaks — uptrend"})
            elif highs[0] > highs[1] > highs[2]:
                patterns.append({"type": "LOWER_HIGHS", "direction": "bearish",
                                 "label": "Lower Highs", "description": "Consecutive lower peaks — downtrend"})
    # Consolidation: tight range in last 4h
    if len(prices) >= 60:
        last_4h = prices[-48:]
        range_pct = (max(last_4h) - min(last_4h)) / min(last_4h) * 100 if min(last_4h) > 0 else 0
        if range_pct < 2:
            patterns.append({"type": "CONSOLIDATION", "direction": "neutral",
                             "label": "Volatility Squeeze", "description": "Tight range building energy — breakout imminent"})

    # Support Test: near 24h low but bouncing
    if len(prices) >= 12:
        if min(recent) <= low_24h * 1.01 and prices[-1] > min(recent) * 1.005:
            patterns.append({"type": "SUPPORT_TEST", "direction": "bullish",
                             "label": f"Support Test ${low_24h:,.0f}", "description": "Price testing and bouncing off 24h low"})

    result = patterns[:3]
    for p in result:
        p["lesson"] = PATTERN_LESSONS.get(p["type"], "")
    return result


# ─── Quality Gates ───────────────────────────────────────────

def _passes_quality_gates(card: dict) -> bool:
    if len(card.get('hook', '')) > 80:
        logger.info(f"Quality gate: hook too long for {card.get('token_symbol')}")
        return False
    if len(card.get('metrics', [])) != 3:
        logger.info(f"Quality gate: need exactly 3 metrics for {card.get('token_symbol')}")
        return False
    if card.get('verdict') not in ('APE', 'FADE', 'DYOR'):
        logger.info(f"Quality gate: invalid verdict for {card.get('token_symbol')}")
        return False
    if card.get('volume_24h', 0) < 5000:
        logger.info(f"Quality gate: low volume for {card.get('token_symbol')}")
        return False
    return True


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

            # Stage 2.5: Chart analysis
            time.sleep(2)  # Rate-limit: CoinGecko ~30 req/min
            chart_prices = fetch_chart_data(token["coingecko_id"])
            sparkline = _build_sparkline(chart_prices) if chart_prices else []
            patterns = detect_patterns(chart_prices) if chart_prices else []

            # Stage 3: Narrative
            narrative = generate_narrative(token, signals, risk_score)

            # Stage 4: Visual (using CoinGecko logo for now)
            # Stage 5: Assemble
            card = assemble_card(token, signals, narrative)
            card["sparkline"] = sparkline
            card["patterns"] = patterns
            if not _passes_quality_gates(card):
                continue
            card_id = insert_card(card)
            if card_id > 0:
                created += 1
                logger.info(f"Card #{card_id}: ${token['token_symbol']} [{narrative['verdict']}] "
                            f"risk={risk_score} — {narrative['hook']}")
                # On-chain signal anchoring
                try:
                    from app.config import get_settings
                    s = get_settings()
                    if s.contract_address:
                        from app.chain import ChainClient
                        from web3 import Web3
                        sym = card["token_symbol"].upper()
                        sym_map = {"BTC": "0x"+"0"*39+"1", "ETH": "0x"+"0"*39+"2", "INIT": "0x"+"0"*39+"3"}
                        asset = sym_map.get(sym, "0x" + Web3.keccak(text=sym).hex()[2:42])
                        is_bull = card.get("verdict", "DYOR") == "APE"
                        conf = min(95, max(50, card.get("risk_score", 70)))
                        p = card.get("price", 0)
                        entry_wei = int(p * 1e18)
                        target_wei = int(p * (1.015 if is_bull else 0.985) * 1e18)
                        dh = Web3.keccak(text=json.dumps({"hook": card.get("hook",""), "verdict": card.get("verdict","")}))
                        chain = ChainClient()
                        sig_id, tx = chain.publish_signal(asset, is_bull, conf, target_wei, entry_wei, dh)
                        from app.db import update_card_signal_id
                        update_card_signal_id(card_id, sig_id)
                        logger.info(f"Anchored card #{card_id} → signal #{sig_id} tx={tx}")
                except Exception as e:
                    logger.warning(f"On-chain anchor failed for card #{card_id}: {e}")
        except Exception as e:
            logger.error(f"Pipeline failed for {token['token_symbol']}: {e}")

    elapsed = time.time() - t0
    logger.info(f"Pipeline complete: {created} cards in {elapsed:.1f}s from {len(new_tokens)} candidates")


def backfill_chart_data():
    """Retry chart data for cards with empty sparkline."""
    from app.db import _get_conn
    import json as _json
    conn = _get_conn()
    if not conn:
        return
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, coingecko_id FROM cards WHERE status = 'active' AND (sparkline IS NULL OR sparkline = '[]'::jsonb) LIMIT 5")
        rows = cur.fetchall()
    if not rows:
        return
    filled = 0
    for row in rows:
        time.sleep(2)
        prices = fetch_chart_data(row["coingecko_id"])
        if not prices:
            continue
        sparkline = _build_sparkline(prices)
        patterns = detect_patterns(prices)
        with conn.cursor() as cur:
            cur.execute("UPDATE cards SET sparkline = %s, patterns = %s WHERE id = %s",
                        (_json.dumps(sparkline), _json.dumps(patterns), row["id"]))
        filled += 1
    if filled:
        logger.info(f"Backfilled chart data for {filled}/{len(rows)} cards")


def _fmt(v: float) -> str:
    if v >= 1e9: return f"${v/1e9:.1f}B"
    if v >= 1e6: return f"${v/1e6:.0f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"
