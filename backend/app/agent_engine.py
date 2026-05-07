"""Multi-agent analysis engine using AWS Bedrock Claude via API Key (Bearer token)."""

import json
import logging

import httpx

logger = logging.getLogger(__name__)

_REGION = "us-east-1"
_MODEL_ID = "us.amazon.nova-lite-v1:0"


def _get_api_key() -> str:
    from app.config import get_settings
    return get_settings().aws_bearer_token_bedrock


def _call_bedrock(system_prompt: str, user_prompt: str) -> str:
    api_key = _get_api_key()
    url = f"https://bedrock-runtime.{_REGION}.amazonaws.com/model/{_MODEL_ID}/converse"
    body = {
        "system": [{"text": system_prompt}],
        "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
    }
    resp = httpx.post(url, json=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }, timeout=60)
    resp.raise_for_status()
    return resp.json()["output"]["message"]["content"][0]["text"]


def _run_technical(token: dict, signals: list, chart_data: list) -> str:
    system = "You are a crypto technical analyst. Analyze EMA crossovers, RSI, MACD, chart patterns. Be concise, data-driven, opinionated. Max 150 words."
    price_data = chart_data[-20:] if chart_data else []
    user = f"${token.get('token_symbol','?')} @ ${token.get('price',0):,.4f}\n24h: {token.get('price_change_24h',0):+.1f}%\nSignals: {json.dumps(signals[:5])}\nRecent prices: {price_data}"
    return _call_bedrock(system, user)


def _run_sentiment(token: dict, sv_context: dict) -> str:
    system = "You are a crypto sentiment/news analyst. Assess ETF flows, breaking news, macro events, social mood. Be concise. Max 150 words."
    user = f"${token.get('token_symbol','?')}\nSosoValue context: {json.dumps(sv_context)}"
    return _call_bedrock(system, user)


def _run_fundamentals(token: dict) -> str:
    system = "You are a crypto fundamentals analyst. Evaluate TVL, supply dynamics, volume/mcap ratio, ecosystem. Be concise. Max 150 words."
    user = f"${token.get('token_symbol','?')}: price=${token.get('price',0):,.4f}, mcap=${token.get('market_cap',0):,.0f}, vol=${token.get('volume_24h',0):,.0f}, circ_supply={token.get('circulating_supply',0)}, total_supply={token.get('total_supply',0)}, tvl={token.get('tvl',0)}"
    return _call_bedrock(system, user)


def _run_debate(technical: str, sentiment: str, fundamentals: str, memory_context: str) -> dict:
    system = (
        "You are a trading debate moderator. Given 3 analyst reports and past accuracy data, "
        "produce a bull case, bear case, and final verdict. Output ONLY JSON:\n"
        '{"bull":"...", "bear":"...", "verdict":"APE or FADE", "confidence":1-100, "reasoning":"..."}'
    )
    user = f"Technical:\n{technical}\n\nSentiment:\n{sentiment}\n\nFundamentals:\n{fundamentals}\n\nPast accuracy:\n{memory_context or 'No history yet.'}"
    raw = _call_bedrock(system, user)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return json.loads(raw)


def _synthesize(token: dict, technical: str, sentiment: str, fundamentals: str, debate: dict) -> dict:
    system = (
        "You produce a JSON trading card for 'Ape or Fade' app. Sarcastic Gen-Z tone. Output ONLY valid JSON with keys: "
        "hook (max 12 words, punchy), roast (1-2 sarcastic sentences), "
        "metrics (array of 3 objects with emoji/label/value/sentiment keys), "
        "verdict (APE/FADE/DYOR), verdict_reason, risk_level (SAFE/MID/DEGEN), risk_score (0-100), "
        "trading_lesson (one specific concept with numbers), why_now (1 sentence), "
        "position_guide, notification_hook (max 15 words), ai_image_prompt, "
        "debate_summary (1 sentence), confidence (int), "
        "trade_plan (object: entry/target/stop/position_size strings). No markdown."
    )
    price = token.get('price', 0)
    user = (
        f"${token.get('token_symbol','?')} @ ${price:,.4f}\n"
        f"Verdict: {debate.get('verdict','DYOR')} (confidence {debate.get('confidence',50)})\n"
        f"Bull: {debate.get('bull','')}\nBear: {debate.get('bear','')}\n"
        f"Technical: {technical}\nSentiment: {sentiment}\nFundamentals: {fundamentals}"
    )
    raw = _call_bedrock(system, user)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return json.loads(raw)


def run_multi_agent_analysis(
    token: dict, signals: list, chart_data: list, sv_context: dict, memory_context: str
) -> dict | None:
    """Run multi-agent analysis. Returns card narrative dict or None on failure."""
    if not _get_api_key():
        logger.debug("No AWS_BEARER_TOKEN_BEDROCK configured, skipping agent analysis")
        return None
    try:
        sym = token.get("token_symbol", "?")
        logger.info("Multi-agent analysis: %s", sym)

        technical = _run_technical(token, signals, chart_data)
        sentiment = _run_sentiment(token, sv_context)
        fundamentals = _run_fundamentals(token)
        debate = _run_debate(technical, sentiment, fundamentals, memory_context)
        result = _synthesize(token, technical, sentiment, fundamentals, debate)

        # Enrich with raw agent reports
        result["agent_reports"] = {"technical": technical, "sentiment": sentiment, "fundamentals": fundamentals}
        result.setdefault("debate_summary", debate.get("reasoning", ""))
        result.setdefault("confidence", debate.get("confidence", 50))

        logger.info("Multi-agent complete: %s → %s (%d%%)", sym, result.get("verdict"), result.get("confidence", 0))
        return result
    except Exception as e:
        logger.warning("Multi-agent failed for %s: %s", token.get("token_symbol", "?"), e)
        return None
