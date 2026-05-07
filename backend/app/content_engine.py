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

# ─── DeFiLlama Data Sources ─────────────────────────────────

_llama_protocols_cache: dict = {}
_llama_protocols_ts: float = 0
_llama_pools_cache: list = []
_llama_pools_ts: float = 0


def _fetch_llama_protocols() -> dict:
    """Fetch DeFiLlama protocols (TVL data). Cached 15 min."""
    global _llama_protocols_cache, _llama_protocols_ts
    if time.time() - _llama_protocols_ts < 900 and _llama_protocols_cache:
        return _llama_protocols_cache
    try:
        resp = httpx.get("https://api.llama.fi/protocols", timeout=15)
        resp.raise_for_status()
        protocols = {p.get("symbol", "").upper(): p for p in resp.json() if p.get("symbol")}
        _llama_protocols_cache = protocols
        _llama_protocols_ts = time.time()
        return protocols
    except Exception as e:
        logger.warning(f"DeFiLlama protocols fetch failed: {e}")
        return _llama_protocols_cache


def _fetch_llama_pools() -> list:
    """Fetch top LP pools from DeFiLlama Yields. Cached 10 min."""
    global _llama_pools_cache, _llama_pools_ts
    if time.time() - _llama_pools_ts < 600 and _llama_pools_cache:
        return _llama_pools_cache
    try:
        resp = httpx.get("https://yields.llama.fi/pools", timeout=20)
        resp.raise_for_status()
        pools = resp.json().get("data", [])
        # Filter: APY > 5%, TVL > $1M, known chains
        filtered = [
            p for p in pools
            if p.get("apy") and p["apy"] > 5
            and p.get("tvlUsd") and p["tvlUsd"] > 1_000_000
            and p.get("symbol")
            and p.get("project")
        ]
        # Sort by attractiveness: high APY + high TVL + low IL
        for p in filtered:
            il = abs(p.get("il7d") or 0)
            apy = p.get("apy", 0)
            tvl = p.get("tvlUsd", 0)
            p["_score"] = apy * min(tvl / 10_000_000, 5) / max(il * 10 + 1, 1)
        filtered.sort(key=lambda p: p["_score"], reverse=True)
        _llama_pools_cache = filtered[:50]
        _llama_pools_ts = time.time()
        return _llama_pools_cache
    except Exception as e:
        logger.warning(f"DeFiLlama pools fetch failed: {e}")
        return _llama_pools_cache


def harvest_pools(limit: int = 5) -> list[dict]:
    """Generate LP pool cards from DeFiLlama yield data."""
    pools = _fetch_llama_pools()
    if not pools:
        return []
    cards = []
    for p in pools[:limit]:
        apy = p.get("apy", 0)
        apy_base = p.get("apyBase") or 0
        apy_reward = p.get("apyReward") or 0
        tvl = p.get("tvlUsd", 0)
        il = abs(p.get("il7d") or 0)
        symbol = p.get("symbol", "???")
        project = p.get("project", "unknown")
        chain = p.get("chain", "unknown")

        # Risk assessment
        if il > 2:
            risk_score, risk_level = 75, "DEGEN"
        elif il > 0.5:
            risk_score, risk_level = 55, "MID"
        else:
            risk_score, risk_level = 30, "SAFE"

        # Verdict
        if apy > 20 and il < 1:
            verdict, verdict_reason = "APE", f"{apy:.1f}% APY with low IL ({il:.2f}%) — strong risk/reward"
        elif apy > 10 and tvl > 10_000_000:
            verdict, verdict_reason = "APE", f"Solid {apy:.1f}% yield on ${tvl/1e6:.0f}M TVL — battle-tested pool"
        elif il > 2 or apy < 5:
            verdict, verdict_reason = "FADE", f"IL risk ({il:.2f}%) outweighs {apy:.1f}% APY — better options exist"
        else:
            verdict, verdict_reason = "DYOR", f"{apy:.1f}% APY but watch IL. Suitable for experienced LPs."

        # Position guide
        if risk_score <= 35:
            pos_guide = "Conservative: 5-10% | Aggressive: 15-20% | Low IL risk"
        elif risk_score <= 60:
            pos_guide = "Conservative: 2-5% | Aggressive: 8-12% | Monitor IL"
        else:
            pos_guide = "Conservative: 1-2% | Aggressive: 3-5% | High IL — hedge or exit early"

        # Trading lesson
        if il > 1:
            lesson = f"Impermanent loss: at ±30% price divergence, you lose ~4.4% vs holding. This pool's 7d IL is {il:.2f}% — factor this into your APY calculation."
        elif apy_reward > apy_base:
            lesson = f"Reward APY ({apy_reward:.1f}%) > base fees ({apy_base:.1f}%). Reward tokens often dump — consider selling rewards immediately to lock in yield."
        else:
            lesson = f"Fee-based yield ({apy_base:.1f}%) is sustainable. Reward-heavy pools ({apy_reward:.1f}%) carry token risk. This pool earns mostly from trading fees — more reliable."

        cards.append({
            "token_symbol": symbol,
            "token_name": f"{project.title()} LP",
            "card_type": "pool",
            "hook": f"{apy:.0f}% APY on {symbol} — {project} ({chain})",
            "roast": f"TVL ${tvl/1e6:.0f}M. Base fees {apy_base:.1f}% + rewards {apy_reward:.1f}%. 7d IL: {il:.2f}%.",
            "metrics": [
                {"emoji": "💰", "label": "APY", "value": f"{apy:.1f}%", "sentiment": "bullish" if apy > 15 else "neutral"},
                {"emoji": "🏦", "label": "TVL", "value": f"${tvl/1e6:.0f}M", "sentiment": "bullish" if tvl > 50e6 else "neutral"},
                {"emoji": "⚠️", "label": "IL 7d", "value": f"{il:.2f}%", "sentiment": "bearish" if il > 1 else "bullish"},
            ],
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "price": apy,  # Use APY as the "price" for display
            "price_change_24h": 0,
            "volume_24h": p.get("volumeUsd1d") or 0,
            "market_cap": tvl,
            "image_url": "",
            "trading_lesson": lesson,
            "position_guide": pos_guide,
            "why_now": f"{symbol} pool on {project} ({chain}) yielding {apy:.1f}% with ${tvl/1e6:.0f}M liquidity",
            "status": "active",
            "source": "defillama",
        })
    return cards


def harvest_tokens(limit: int = 10) -> list[dict]:
    """Fetch token data from CoinGecko — multiple orderings for diversity."""
    all_tokens = {}
    orderings = ["volume_desc", "market_cap_desc", "market_cap_change_24h_desc"]
    for order in orderings:
        try:
            resp = httpx.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": order, "per_page": limit,
                        "page": 1, "sparkline": False, "price_change_percentage": "1h,24h"},
                timeout=15,
            )
            resp.raise_for_status()
            for c in resp.json():
                parsed = _parse_coingecko(c)
                all_tokens[parsed["coingecko_id"]] = parsed
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Harvest ({order}) failed: {e}")
    tokens = list(all_tokens.values())
    # Sort by "interestingness" — anomaly-first, not just volume
    for t in tokens:
        score = 0
        vol_mcap = t["volume_24h"] / max(t["market_cap"], 1)
        if vol_mcap > 0.3: score += 30
        if abs(t.get("price_change_1h") or 0) > 5: score += 25
        if abs(t["price_change_24h"]) > 10: score += 20
        if t["circulating_supply"] > 0 and t["total_supply"] > 0 and t["circulating_supply"] / t["total_supply"] < 0.5: score += 15
        t["interest_score"] = score
    tokens.sort(key=lambda t: t["interest_score"], reverse=True)
    from app.sosovalue_client import get_full_context
    sv_ctx = get_full_context()
    if sv_ctx:
        for t in tokens:
            t["sosovalue"] = sv_ctx
    # Enrich with DeFiLlama TVL data
    protocols = _fetch_llama_protocols()
    if protocols:
        for t in tokens:
            proto = protocols.get(t["token_symbol"])
            if proto:
                t["tvl"] = proto.get("tvl") or 0
                t["tvl_change_1d"] = proto.get("change_1d") or 0
                t["mcap_tvl_ratio"] = round(t["market_cap"] / max(proto.get("tvl") or 1, 1), 2)
    return tokens


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

    # DeFiLlama: TVL signals
    tvl = token.get("tvl", 0)
    tvl_change = token.get("tvl_change_1d", 0)
    if tvl > 0 and tvl_change:
        if tvl_change > 10:
            signals.append({"type": "TVL_SURGE", "severity": 4, "direction": "bullish", "emoji": "🏦",
                            "finding": f"TVL up {tvl_change:.0f}% in 24h — capital flowing in"})
        elif tvl_change < -10:
            signals.append({"type": "TVL_DRAIN", "severity": 4, "direction": "bearish", "emoji": "🚨",
                            "finding": f"TVL down {abs(tvl_change):.0f}% in 24h — capital fleeing"})
    mcap_tvl = token.get("mcap_tvl_ratio", 0)
    if mcap_tvl > 10:
        signals.append({"type": "OVERVALUED_VS_TVL", "severity": 3, "direction": "bearish", "emoji": "📊",
                        "finding": f"MCap/TVL ratio {mcap_tvl:.1f}x — potentially overvalued vs locked value"})

    # SosoValue: ETF flow + macro event signals
    sv = token.get("sosovalue", {})
    etf = sv.get("etf_flows", {})
    if token["token_symbol"] in ("BTC", "ETH"):
        flow = etf.get(f"{token['token_symbol'].lower()}_net_flow", 0)
        if flow and abs(flow) > 50_000_000:
            d = "bullish" if flow > 0 else "bearish"
            signals.append({"type": "ETF_FLOW", "severity": min(5, int(abs(flow) / 100_000_000) + 2),
                            "direction": d, "emoji": "🏦",
                            "finding": f"ETF net flow: ${flow/1e6:+.0f}M today"})
    for evt in sv.get("macro_events", [])[:1]:
        signals.append({"type": "MACRO_CATALYST", "severity": 3,
                        "direction": "neutral", "emoji": "📅",
                        "finding": f"Macro: {evt.get('name', 'Event')} today"})

    return sorted(signals, key=lambda s: s["severity"], reverse=True)


def compute_risk_score(signals: list[dict]) -> tuple[int, list[dict]]:
    """0-100. Higher = riskier. Returns (score, breakdown)."""
    base = 50
    breakdown = []
    for s in signals:
        if s["direction"] == "bearish":
            delta = s["severity"] * 5
            base += delta
            breakdown.append({"factor": s["finding"], "impact": f"+{delta}", "direction": "risk"})
        elif s["direction"] == "bullish":
            delta = s["severity"] * 3
            base -= delta
            breakdown.append({"factor": s["finding"], "impact": f"-{delta}", "direction": "safe"})
    return max(0, min(100, base)), breakdown


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

def generate_narrative(token: dict, signals: list[dict], risk_score: int, risk_breakdown: list[dict] | None = None) -> dict:
    """Try Claude Bedrock, fall back to templates."""
    verdict, verdict_reason, risk_level = compute_verdict(signals, risk_score)
    content = _narrative_via_bedrock(token, signals, verdict, risk_level)
    if not content:
        content = _narrative_fallback(token, signals, verdict, risk_level)
    content["verdict"] = verdict
    content["verdict_reason"] = verdict_reason
    content["risk_level"] = risk_level
    content["risk_score"] = risk_score
    content["risk_breakdown"] = risk_breakdown or []
    return content


def _narrative_via_bedrock(token: dict, signals: list[dict], verdict: str, risk_level: str) -> dict | None:
    settings = get_settings()
    signal_lines = "\n".join(f"- [{s['severity']}/5 {s['direction']}] {s['finding']}" for s in signals[:5])
    # SosoValue institutional context for Claude
    sv = token.get("sosovalue", {})
    sv_lines = ""
    etf = sv.get("etf_flows", {})
    if etf.get("btc_net_flow"):
        sv_lines += f"BTC ETF flow: ${etf['btc_net_flow']/1e6:+.0f}M. "
    for n in sv.get("hot_news", [])[:1]:
        sv_lines += f"News: {n.get('title', '')}. "
    for m in sv.get("macro_events", [])[:1]:
        sv_lines += f"Macro: {m.get('name', '')}. "
    prompt = (
        f'You are the AI of "Ape or Fade" — savage, sarcastic, brilliant crypto analyst. '
        f'Gen-Z tone. Never boring. Take a stance.\n\n'
        f'Token: {token["token_name"]} (${token["token_symbol"]})\n'
        f'Price: ${token["price"]:,.6f}, 1h: {token.get("price_change_1h",0):+.1f}%, '
        f'24h: {token["price_change_24h"]:+.1f}%\n'
        f'Vol: ${token["volume_24h"]:,.0f}, MCap: ${token["market_cap"]:,.0f}\n'
        f'Verdict: {verdict}, Risk: {risk_level}\n'
        f'Signals:\n{signal_lines}\n\n'
        + (f'Institutional context: {sv_lines}\n' if sv_lines else '')
        + f'IMPORTANT: Include a trading_lesson (one specific concept with numbers), why_now (why this token is interesting right now), and position_guide (suggested % of portfolio based on risk {risk_level}).\n'
        + f'Respond ONLY with JSON:\n'
        f'{{"hook":"punchy scroll-stopper max 12 words",'
        f'"roast":"1-2 sarcastic sentences with data insights",'
        f'"metrics":[{{"emoji":"X","label":"Y","value":"Z","sentiment":"bullish|bearish|neutral"}},'
        f'{{"emoji":"X","label":"Y","value":"Z","sentiment":"bullish|bearish|neutral"}},'
        f'{{"emoji":"X","label":"Y","value":"Z","sentiment":"bullish|bearish|neutral"}}],'
        f'"trading_lesson":"ONE specific trading concept this setup demonstrates with numbers",'
        f'"why_now":"specific reason this token is interesting RIGHT NOW in 1 sentence",'
        f'"position_guide":"Conservative: X% | Aggressive: Y% of portfolio",'
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


def _position_guide(risk_score: int) -> str:
    if risk_score <= 30:
        return "Conservative: 3-5% | Aggressive: 8-10% | Low risk setup"
    elif risk_score <= 60:
        return "Conservative: 1-3% | Aggressive: 5-7% | Medium risk"
    return "Conservative: 0.5-1% | Aggressive: 2-3% | High risk — small size only"


def _generate_why_now(token: dict, signals: list) -> str:
    sym = token['token_symbol']
    pct = token['price_change_24h']
    vol_mcap = token['volume_24h'] / max(token['market_cap'], 1)
    if vol_mcap > 0.3:
        return f"${sym} volume is {vol_mcap:.1f}x market cap — unusual accumulation/distribution happening now"
    if abs(token.get('price_change_1h') or 0) > 5:
        return f"${sym} moved {token['price_change_1h']:+.1f}% in 1 hour — momentum event in progress"
    if abs(pct) > 10:
        return f"${sym} {pct:+.1f}% in 24h — strong directional move with follow-through potential"
    sv = token.get('sosovalue', {})
    if sv.get('etf_flows', {}).get('btc_net_flow', 0) > 100e6:
        return f"BTC ETF inflow ${sv['etf_flows']['btc_net_flow']/1e6:.0f}M — institutional buying lifts all boats"
    return f"${sym} showing {signals[0]['finding'] if signals else 'mixed signals'} — watch for confirmation"


def _generate_lesson(signals: list, token: dict) -> str:
    if not signals:
        return "No clear setup — patience is a trading edge. Wait for confluence."
    top = signals[0]
    lessons = {
        'VOLUME_SPIKE': f"Volume precedes price. When vol/mcap > 0.3x, expect 5-15% move within 24h.",
        'PRICE_MOMENTUM': f"Momentum is mean-reverting short-term but trend-following long-term. 1h moves > 5% often retrace 40-60%.",
        'BUY_SELL_IMBALANCE': f"Price near 24h high = buyers in control. Breakouts above resistance often run 2-5% before pullback.",
        'HOLDER_CONCENTRATION': f"Low circulating supply (<50%) = unlock risk. Insiders can dump at any time.",
        'MCAP_TO_VOLUME_RATIO': f"Volume > 2x market cap signals extreme speculation. High reward but expect 30%+ drawdowns.",
        'ETF_FLOW': f"ETF flows are a leading indicator. $100M+ daily flow historically precedes 3-7% moves within 48h.",
        'MACRO_CATALYST': f"Macro events (Fed, CPI) cause volatility spikes. Reduce position size 50% before announcements.",
    }
    return lessons.get(top['type'], f"Pattern: {top['type']} — {top['finding']}. Track outcomes to build your edge.")


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
            "ai_image_prompt": f"{sym} crypto {'rocket launch' if verdict == 'APE' else 'crash landing' if verdict == 'FADE' else 'foggy crossroads'}",
            "trading_lesson": _generate_lesson(signals, token),
            "why_now": _generate_why_now(token, signals),
            "position_guide": _position_guide(compute_risk_score(signals)[0])}




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


_pattern_stats_cache: dict = {}
_pattern_stats_ts: float = 0

def _get_pattern_stats(signals: list[dict]) -> dict | None:
    """Get historical outcome stats for the primary signal type."""
    global _pattern_stats_cache, _pattern_stats_ts
    import time as _t
    if _t.time() - _pattern_stats_ts > 3600:  # refresh hourly
        try:
            from app.db import _get_conn
            conn = _get_conn()
            if conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT pattern, COUNT(*) as n, 
                        AVG(CASE WHEN resolved AND exit_price::numeric > entry_price::numeric THEN 1.0 ELSE 0.0 END) as win_rate
                        FROM signals WHERE resolved = true AND pattern IS NOT NULL
                        GROUP BY pattern HAVING COUNT(*) >= 5""")
                    _pattern_stats_cache = {r[0]: {"samples": r[1], "win_rate": round(float(r[2] or 0) * 100, 1)} for r in cur.fetchall()}
                    _pattern_stats_ts = _t.time()
        except Exception:
            pass
    if not signals:
        return None
    top_pattern = signals[0].get("type", "")
    stats = _pattern_stats_cache.get(top_pattern)
    if stats:
        return {"pattern": top_pattern, "win_rate": stats["win_rate"], "samples": stats["samples"]}
    return None


# ─── Stage 5: Card Assembler ────────────────────────────────

def assemble_card(token: dict, signals: list[dict], narrative: dict) -> dict:
    """Merge all pipeline outputs into final card object."""
    card = {
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
        "pattern_stats": _get_pattern_stats(signals),
        "risk_breakdown": narrative.get("risk_breakdown", []),
    }
    # Enrich with SoSoValue institutional context
    sv = token.get("sosovalue", {})
    if sv:
        inst = []
        btc_flow = sv.get("etf_flows", {}).get("btc_net_flow", 0)
        if btc_flow and abs(btc_flow) > 10_000_000:
            inst.append({"emoji": "\U0001f3e6", "label": "BTC ETF Flow",
                         "value": f"${btc_flow/1e6:+.0f}M",
                         "sentiment": "bullish" if btc_flow > 0 else "bearish"})
        news = sv.get("hot_news", [])
        if news:
            inst.append({"emoji": "\U0001f4f0", "label": "Breaking",
                         "value": news[0].get("title", "")[:40], "sentiment": "neutral"})
        macro = sv.get("macro_events", [])
        if macro:
            inst.append({"emoji": "\U0001f4c5", "label": "Macro",
                         "value": macro[0].get("name", "")[:30], "sentiment": "neutral"})
        if inst:
            card["institutional_context"] = inst
    return card


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
    for token in new_tokens[:8]:
        try:
            # Stage 2: Analyze signals
            signals = analyze_signals(token)
            risk_score, risk_breakdown = compute_risk_score(signals)

            # Skip boring tokens (no notable signals)
            if signals and max(s["severity"] for s in signals) < 2:
                continue

            # Stage 2.5: Chart analysis
            time.sleep(2)  # Rate-limit: CoinGecko ~30 req/min
            chart_prices = fetch_chart_data(token["coingecko_id"])
            sparkline = _build_sparkline(chart_prices) if chart_prices else []
            patterns = detect_patterns(chart_prices) if chart_prices else []

            # Stage 3: Multi-Agent Narrative (fallback to simple narrative)
            from app.agent_memory import get_accuracy_context
            memory_ctx = get_accuracy_context(token["token_symbol"])
            from app.agent_engine import run_multi_agent_analysis
            narrative = run_multi_agent_analysis(token, signals, chart_prices, token.get("sosovalue", {}), memory_ctx)
            if not narrative:
                narrative = generate_narrative(token, signals, risk_score, risk_breakdown)

            # Stage 4: Visual (using CoinGecko logo for now)
            # Stage 5: Assemble
            card = assemble_card(token, signals, narrative)
            card["sparkline"] = sparkline
            card["patterns"] = patterns
            if not _passes_quality_gates(card):
                continue
            card_id = insert_card(card)
            # Track prediction for accuracy feedback
            if card_id > 0:
                try:
                    from app.agent_memory import store_prediction
                    store_prediction(card)
                except Exception:
                    pass
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

    # Generate LP pool cards
    try:
        pool_cards = harvest_pools(3)
        for card in pool_cards:
            try:
                insert_card(card)
                logger.info(f"Pool card: {card['token_symbol']} ({card['verdict']})")
            except Exception as e:
                logger.warning(f"Pool card insert failed: {e}")
    except Exception as e:
        logger.warning(f"Pool card generation failed: {e}")


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


# ─── Signal-to-Card Bridge ──────────────────────────────────

def _fetch_single_token(symbol: str, coingecko_id: str) -> dict | None:
    """Fetch data for a single token from CoinGecko."""
    if not coingecko_id:
        return None
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": coingecko_id,
                    "sparkline": False, "price_change_percentage": "1h,24h"},
            timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return _parse_coingecko(data[0]) if data else None
    except Exception as e:
        logger.warning(f"Single token fetch failed for {symbol}: {e}")
        return None


def generate_card_from_signal(signal_id: int) -> int:
    """Generate a card from a provider signal. Returns card_id or -1."""
    from app.db import get_signal_by_id, insert_card
    from app.signal_engine import COINGECKO_IDS

    signal = get_signal_by_id(signal_id)
    if not signal:
        return -1

    sym = (signal.get("symbol", "") or signal.get("asset", "").replace("/USD", "")).upper()
    cg_id = COINGECKO_IDS.get(f"{sym}/USD", "")

    # Fetch token data or build fallback
    token = _fetch_single_token(sym, cg_id)
    if not token:
        try:
            price = float(signal["entryPrice"])
        except (ValueError, TypeError):
            price = 0
        token = {"coingecko_id": cg_id, "token_symbol": sym, "token_name": sym,
                 "price": price, "price_change_1h": 0, "price_change_24h": 0,
                 "volume_24h": 0, "market_cap": 0, "image_url": "",
                 "high_24h": 0, "low_24h": 0, "circulating_supply": 0, "total_supply": 0}

    is_bull = signal.get("isBull", True)
    verdict = "APE" if is_bull else "FADE"
    risk_score = max(5, 100 - signal.get("confidence", 70))

    # Narrate: full mode (provider analysis) vs quick mode (AI)
    signals_data = analyze_signals(token)
    _, risk_breakdown = compute_risk_score(signals_data)
    narrative = generate_narrative(token, signals_data, risk_score, risk_breakdown)
    narrative["verdict"] = verdict

    if signal.get("analysis", "").strip():
        narrative["roast"] = signal["analysis"]

    # Inject TP/SL metric
    try:
        tp, sl, entry = float(signal["targetPrice"]), float(signal["stopLoss"]), float(signal["entryPrice"])
        if tp > 0 and sl > 0 and entry > 0:
            tp_pct = round(abs(tp - entry) / entry * 100, 1)
            sl_pct = round(abs(entry - sl) / entry * 100, 1)
            tp_sl_metric = {"emoji": "🎯", "label": "TP/SL",
                            "value": f"+{tp_pct}% / -{sl_pct}%", "sentiment": "neutral"}
            metrics = narrative.get("metrics", [])
            if len(metrics) >= 3:
                metrics[2] = tp_sl_metric
            else:
                metrics.append(tp_sl_metric)
            narrative["metrics"] = metrics
    except (ValueError, TypeError):
        pass

    card = assemble_card(token, signals_data, narrative)

    # Chart data
    if cg_id:
        time.sleep(2)
        chart_prices = fetch_chart_data(cg_id)
        card["sparkline"] = _build_sparkline(chart_prices) if chart_prices else []
        card["patterns"] = detect_patterns(chart_prices) if chart_prices else []

    card["source"] = "provider"
    card["provider"] = signal.get("provider", "")
    card["signal_id"] = signal_id

    card_id = insert_card(card)
    if card_id > 0:
        logger.info(f"Provider card #{card_id} from signal #{signal_id}: ${sym} [{verdict}]")
    return card_id


def generate_index_cards() -> list[dict]:
    """Generate index-based cards from SosoValue SSI indices."""
    try:
        from app.sosovalue_client import get_index_list, get_index_snapshot
        indices = get_index_list()
        if not indices:
            return []
        cards = []
        INDEX_NAMES = {"ssimag7": "Magnificent 7", "ssimeme": "Meme Index", "ssidefi": "DeFi Blue Chips",
                       "ssilayer1": "Layer 1", "ssilayer2": "Layer 2", "ssiai": "AI Tokens",
                       "ssinft": "NFT Index", "ssigamefi": "GameFi", "ssirwa": "RWA",
                       "ssisocialfi": "SocialFi", "ssidepin": "DePIN", "ssicefi": "CeFi", "ssipayfi": "PayFi"}
        for ticker in indices[:5]:
            name = INDEX_NAMES.get(ticker.lower(), ticker.upper())
            snap = get_index_snapshot(ticker)
            pct = float(snap.get("priceChangePercent24h", 0)) if snap else 0
            price = float(snap.get("price", 0)) if snap else 0
            direction = "pumping 🚀" if pct > 2 else "dumping 📉" if pct < -2 else "crabbing 🦀"
            cards.append({
                "token_symbol": f"{ticker.upper()}.ssi",
                "token_name": f"{name} Index",
                "card_type": "index",
                "hook": f"{name} is {direction}",
                "roast": f"Basket of top tokens — {pct:+.1f}% today. Diversification isn't a meme.",
                "metrics": [{"emoji": "📈", "label": "24h", "value": f"{pct:+.1f}%"},
                            {"emoji": "💰", "label": "Price", "value": f"${price:.2f}"}],
                "price": price, "price_change_24h": pct, "volume_24h": 0, "market_cap": 0,
                "status": "active",
            })
        return cards
    except Exception as e:
        logger.warning(f"Index card generation failed: {e}")
        return []
