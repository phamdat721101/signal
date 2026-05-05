import logging, time, httpx
from app.config import get_settings

log = logging.getLogger(__name__)
_BASE = "https://openapi.sosovalue.com/openapi/v1"
_cache: dict[str, tuple[float, any]] = {}


def _is_enabled() -> bool:
    return bool(getattr(get_settings(), "sosovalue_api_key", ""))


def _get(path: str, params: dict | None = None, cache_key: str = "", ttl: int = 300) -> dict | None:
    now = time.time()
    if cache_key and cache_key in _cache and now - _cache[cache_key][0] < ttl:
        return _cache[cache_key][1]
    try:
        r = httpx.get(f"{_BASE}{path}", params=params, headers={"x-soso-api-key": get_settings().sosovalue_api_key}, timeout=10)
        body = r.json()
        if body.get("code") != 0:
            log.warning("SosoValue %s error: %s", path, body.get("message"))
            return None
        data = body.get("data")
        if cache_key:
            _cache[cache_key] = (now, data)
        return data
    except Exception as e:
        log.warning("SosoValue %s failed: %s", path, e)
        return None


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
    return [{"title": item.get("title", "")} for item in items[:limit]]


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
