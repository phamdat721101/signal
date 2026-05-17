import logging, time
from app.config import get_settings
from app import http_client

log = logging.getLogger(__name__)
_BASE = "https://openapi.sosovalue.com/openapi/v1"
_cache: dict[str, tuple[float, any]] = {}
_req_timestamps: list[float] = []
_analysis_404_cache: set = set()


def _rate_limit_remaining() -> int:
    now = time.time()
    _req_timestamps[:] = [t for t in _req_timestamps if now - t < 60]
    return max(0, 18 - len(_req_timestamps))


def _is_enabled() -> bool:
    return bool(getattr(get_settings(), "sosovalue_api_key", ""))


def _get(path: str, params: dict | None = None, cache_key: str = "", ttl: int = 300) -> dict | None:
    """SoSoValue GET. Cached when cache_key set. Retry+breaker via http_client."""
    now = time.time()
    if cache_key and cache_key in _cache and now - _cache[cache_key][0] < ttl:
        return _cache[cache_key][1]
    _req_timestamps.append(now)
    r = http_client.get(
        f"{_BASE}{path}",
        service="sosovalue",
        params=params,
        headers={"x-soso-api-key": get_settings().sosovalue_api_key},
    )
    if r is None:
        return None  # http_client already logged + tracked the failure
    try:
        body = r.json()
    except Exception as e:
        log.warning("SosoValue %s: invalid JSON: %s", path, e)
        return None
    if body.get("code") != 0:
        log.warning("SosoValue %s api error: %s", path, body.get("message"))
        return None
    data = body.get("data")
    if cache_key:
        _cache[cache_key] = (now, data)
    return data


def get_etf_flows() -> dict:
    entry = _cache.get("etf_flows")
    if entry and time.time() - entry[0] < 600:
        return entry[1]
    result = {}
    for symbol in ("BTC", "ETH"):
        data = _get("/etfs/summary-history", params={"symbol": symbol, "country_code": "US"}, cache_key="", ttl=600)
        if data and isinstance(data, list) and data:
            rec = data[-1]
            flow_key = f"{symbol.lower()}_net_flow"
            result[flow_key] = float(rec.get("total_net_inflow", 0) or 0)
    _cache["etf_flows"] = (time.time(), result)
    return result


def get_hot_news(limit: int = 5) -> list:
    data = _get("/news/hot", params={"page_size": limit}, cache_key="hot_news", ttl=300)
    items = data.get("list", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    return [{"title": item.get("title", ""), "image_url": item.get("coverImage", "") or item.get("thumbnail", "") or item.get("image", "")} for item in items[:limit]]


def get_macro_events() -> list:
    today = time.strftime("%Y-%m-%d")
    data = _get("/macro/events", params={"date": today}, cache_key=f"macro_{today}", ttl=600)
    if not data or not isinstance(data, list):
        return []
    # API returns [{date, events: ["event1", "event2"]}] — flatten to [{name, impact}]
    events = []
    for day in data:
        for evt in day.get("events", []):
            name = evt if isinstance(evt, str) else evt.get("name", str(evt))
            events.append({"name": name, "impact": "medium"})
    return events


def get_sosovalue_context() -> dict:
    if not _is_enabled():
        return {}
    return {"etf_flows": get_etf_flows(), "hot_news": get_hot_news(), "macro_events": get_macro_events()}


def refresh_cache():
    get_sosovalue_context()


# ─── Module A: Expanded SoSoValue Client ─────────────────────


def get_index_list() -> list:
    if not _is_enabled():
        return []
    data = _get("/indices", cache_key="index_list", ttl=900)
    return data if isinstance(data, list) else []


def get_index_snapshot(ticker: str) -> dict | None:
    if not _is_enabled():
        return None
    return _get(f"/indices/{ticker}/market-snapshot", cache_key=f"idx_{ticker}", ttl=60)


def get_index_constituents(ticker: str) -> list:
    if not _is_enabled():
        return []
    data = _get(f"/indices/{ticker}/constituents", cache_key=f"idx_const_{ticker}", ttl=900)
    return data if isinstance(data, list) else []


def get_btc_treasuries() -> list:
    if not _is_enabled():
        return []
    data = _get("/btc-treasuries", cache_key="btc_treasuries", ttl=900)
    return data if isinstance(data, list) else []


def get_featured_news() -> list:
    if not _is_enabled():
        return []
    data = _get("/news/featured", cache_key="featured_news", ttl=300)
    if isinstance(data, dict):
        return data.get("list", [])
    return data if isinstance(data, list) else []


def get_sector_spotlight() -> dict | None:
    if not _is_enabled():
        return None
    return _get("/currencies/sector-spotlight", cache_key="sector_spotlight", ttl=600)


def get_currency_snapshot(currency_id: str) -> dict | None:
    if not _is_enabled():
        return None
    return _get(f"/currencies/{currency_id}/market-snapshot", cache_key=f"curr_{currency_id}", ttl=60)


def get_analysis(chart_name: str) -> dict | None:
    if not _is_enabled():
        return None
    if chart_name in _analysis_404_cache:
        return None
    result = _get(f"/analyses/{chart_name}", cache_key=f"analysis_{chart_name}", ttl=300)
    if result is None:
        _analysis_404_cache.add(chart_name)
    return result


def get_currency_snapshots_batch(ids: list[str], max_n: int = 10) -> dict[str, dict]:
    if not _is_enabled():
        return {}
    results = {}
    for cid in ids[:max_n]:
        if _rate_limit_remaining() <= 2:
            break
        snap = get_currency_snapshot(cid)
        if snap:
            results[cid] = snap
        time.sleep(0.5)
    return results


def get_full_context() -> dict:
    """Merge all SoSoValue data into a single context dict."""
    if not _is_enabled():
        return {}
    base = get_sosovalue_context()
    base["indices"] = get_index_list()
    base["btc_treasuries"] = get_btc_treasuries()
    base["featured_news"] = get_featured_news()
    base["sector_spotlight"] = get_sector_spotlight()
    return base


# ─── Upgrade 1: ETF Flow Momentum (3-day rolling streak) ─────

_etf_history: list[dict] = []  # [{date, btc_flow, eth_flow}]


def get_etf_momentum() -> dict:
    """Detect multi-day ETF flow streaks. Returns momentum signals."""
    global _etf_history
    flows = get_etf_flows()
    if not flows:
        return {}
    today = time.strftime("%Y-%m-%d")
    # Append today's flow if not already recorded
    if not _etf_history or _etf_history[-1].get("date") != today:
        _etf_history.append({"date": today, "btc": flows.get("btc_net_flow", 0), "eth": flows.get("eth_net_flow", 0)})
    _etf_history[:] = _etf_history[-7:]  # keep 7 days max
    result = {}
    for sym in ("btc", "eth"):
        recent = [d[sym] for d in _etf_history[-3:] if d.get(sym)]
        if len(recent) < 2:
            continue
        streak = sum(1 for f in recent if f > 0) if recent[-1] > 0 else -sum(1 for f in recent if f < 0)
        total = sum(recent)
        if abs(streak) >= 2:
            result[f"{sym}_streak"] = streak
            result[f"{sym}_total_3d"] = total
            result[f"{sym}_direction"] = "inflow" if streak > 0 else "outflow"
    return result


# ─── Upgrade 3: Whale Accumulation Delta Tracking ────────────

_prev_treasuries: dict[str, float] = {}


def get_whale_deltas() -> list[dict]:
    """Detect BTC treasury changes between refreshes."""
    global _prev_treasuries
    treasuries = get_btc_treasuries()
    if not treasuries:
        return []
    deltas = []
    for t in treasuries[:10]:
        name = t.get("name", "Unknown")
        held = float(t.get("totalHoldings", 0) or t.get("btcAmount", 0) or 0)
        if not held:
            continue
        prev = _prev_treasuries.get(name, 0)
        if prev > 0 and held != prev:
            change = held - prev
            pct = (change / prev) * 100
            if abs(pct) > 0.1:  # >0.1% change is meaningful
                deltas.append({"name": name, "btc_held": held, "change_btc": change, "change_pct": pct})
        _prev_treasuries[name] = held
    return sorted(deltas, key=lambda d: abs(d["change_btc"]), reverse=True)


# ─── Upgrade 4: Research Conviction Score ────────────────────

def get_research_conviction(symbol: str) -> dict | None:
    """Extract quantitative conviction from SosoValue analysis."""
    analysis = get_analysis(symbol.lower())
    if not analysis:
        return None
    # Extract signals from analysis data
    score = 50  # neutral baseline
    factors = []
    summary = analysis.get("summary", "") or analysis.get("conclusion", "") or ""
    # Keyword-based scoring from research text
    bullish_kw = ["strong buy", "bullish", "accumulate", "outperform", "breakout", "uptrend"]
    bearish_kw = ["sell", "bearish", "avoid", "underperform", "breakdown", "downtrend"]
    text = (summary + " " + str(analysis.get("keyFindings", ""))).lower()
    for kw in bullish_kw:
        if kw in text:
            score += 8
            factors.append(f"Research: {kw}")
    for kw in bearish_kw:
        if kw in text:
            score -= 8
            factors.append(f"Research: {kw}")
    return {"score": max(0, min(100, score)), "factors": factors[:3], "summary": summary[:200]}


def get_sector_tokens(limit: int = 30) -> list[dict]:
    """Fetch tokens from hot sectors via sector-spotlight + index constituents."""
    if not _is_enabled():
        return []
    spotlight = get_sector_spotlight()
    if not spotlight:
        return []
    sectors = spotlight if isinstance(spotlight, list) else spotlight.get("sectors", [])
    tokens: list[dict] = []
    seen: set = set()
    for sector in sectors[:3]:
        ticker = sector.get("indexTicker") or sector.get("ticker", "")
        sector_name = sector.get("name", "")
        if not ticker or _rate_limit_remaining() < 2:
            break
        constituents = get_index_constituents(ticker)
        for c in constituents:
            sym = (c.get("symbol") or c.get("ticker", "")).upper()
            if sym and sym not in seen:
                seen.add(sym)
                tokens.append({
                    "coingecko_id": c.get("coingeckoId", sym.lower()),
                    "token_symbol": sym,
                    "token_name": c.get("name", sym),
                    "price": float(c.get("price", 0) or 0),
                    "price_change_24h": float(c.get("priceChangePercent24h", 0) or 0),
                    "price_change_1h": 0,
                    "volume_24h": float(c.get("volume24h", 0) or 0),
                    "market_cap": float(c.get("marketCap", 0) or 0),
                    "image_url": c.get("logoUrl", ""),
                    "high_24h": 0, "low_24h": 0,
                    "circulating_supply": 0, "total_supply": 0,
                    "sector": sector_name,
                    "index_membership": [ticker],
                    "interest_score": 20,
                })
    return tokens[:limit]
