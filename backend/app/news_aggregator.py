"""News Aggregator — multi-source crypto news with sentiment scoring.

Sources: SosoValue (primary) + CryptoPanic (community votes) + cryptocurrency.cv (free RSS).
"""

import logging
import time
import httpx
from app.config import get_settings

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, list]] = {}
_CACHE_TTL = 300  # 5 min

# ─── Sentiment Keywords ───────────────────────────────────────
_BULL_WORDS = {"bullish", "rally", "surge", "breakout", "inflow", "accumulation", "buy",
               "pump", "moon", "ath", "adoption", "partnership", "upgrade", "approval"}
_BEAR_WORDS = {"bearish", "crash", "dump", "outflow", "sell-off", "liquidation", "sell",
               "hack", "exploit", "ban", "lawsuit", "sec", "fraud", "rug", "delay"}


def _score_title(title: str) -> int:
    """Score a news title from -100 to +100 using keyword matching."""
    t = title.lower()
    bull = sum(1 for w in _BULL_WORDS if w in t)
    bear = sum(1 for w in _BEAR_WORDS if w in t)
    if bull + bear == 0:
        return 0
    return int((bull - bear) / (bull + bear) * 100)


def _cached(key: str) -> list | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


# ─── Source: SosoValue ────────────────────────────────────────
def _fetch_sosovalue() -> list[dict]:
    from app.sosovalue_client import get_hot_news, get_featured_news, _is_enabled
    if not _is_enabled():
        return []
    items = []
    for n in get_hot_news(10) + get_featured_news():
        title = n.get("title", "")
        if not title:
            continue
        items.append({
            "title": title,
            "source": "sosovalue",
            "sentiment_score": _score_title(title),
            "image_url": n.get("image_url", ""),
            "timestamp": int(time.time()),
        })
    return items


# ─── Source: CryptoPanic ──────────────────────────────────────
def _fetch_cryptopanic() -> list[dict]:
    key = getattr(get_settings(), "cryptopanic_api_key", "")
    if not key:
        return []
    cached = _cached("cryptopanic")
    if cached is not None:
        return cached
    try:
        resp = httpx.get(
            "https://cryptopanic.com/api/free/v1/posts/",
            params={"auth_token": key, "filter": "hot", "public": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        items = []
        for post in resp.json().get("results", [])[:20]:
            title = post.get("title", "")
            # CryptoPanic has community votes
            votes = post.get("votes", {})
            positive = votes.get("positive", 0)
            negative = votes.get("negative", 0)
            vote_score = 0
            if positive + negative > 0:
                vote_score = int((positive - negative) / (positive + negative) * 50)
            keyword_score = _score_title(title)
            # Blend keyword + community votes
            score = int(keyword_score * 0.6 + vote_score * 0.4)
            currencies = [c.get("code", "") for c in post.get("currencies", [])]
            items.append({
                "title": title,
                "source": "cryptopanic",
                "sentiment_score": max(-100, min(100, score)),
                "tokens": currencies,
                "timestamp": int(time.time()),
            })
        _cache["cryptopanic"] = (time.time(), items)
        return items
    except Exception as e:
        log.warning("CryptoPanic fetch failed: %s", e)
        return []


# ─── Source: cryptocurrency.cv ────────────────────────────────
_cryptocv_disabled = False  # auto-disable on 402/payment errors


def _fetch_cryptocv() -> list[dict]:
    global _cryptocv_disabled
    if _cryptocv_disabled:
        return []
    cached = _cached("cryptocv")
    if cached is not None:
        return cached
    try:
        resp = httpx.get("https://cryptocurrency.cv/api/v1/news?limit=20", timeout=10)
        if resp.status_code == 402:
            _cryptocv_disabled = True
            log.info("cryptocurrency.cv requires payment — disabled")
            return []
        resp.raise_for_status()
        items = []
        for article in resp.json().get("articles", resp.json() if isinstance(resp.json(), list) else [])[:20]:
            title = article.get("title", "")
            if not title:
                continue
            items.append({
                "title": title,
                "source": "cryptocv",
                "sentiment_score": _score_title(title),
                "tokens": article.get("tokens", []),
                "timestamp": int(time.time()),
            })
        _cache["cryptocv"] = (time.time(), items)
        return items
    except Exception as e:
        log.warning("cryptocurrency.cv fetch failed: %s", e)
        return []


# ─── Public API ───────────────────────────────────────────────
def fetch_all_news() -> list[dict]:
    """Fetch and merge news from all sources. Deduplicates by title similarity."""
    all_items = _fetch_sosovalue() + _fetch_cryptopanic() + _fetch_cryptocv()
    # Deduplicate by normalized title prefix (first 40 chars)
    seen: set[str] = set()
    unique = []
    for item in all_items:
        key = item["title"][:40].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def get_token_news(symbol: str, limit: int = 10) -> list[dict]:
    """Get news relevant to a specific token."""
    sym = symbol.upper()
    all_news = fetch_all_news()
    relevant = [
        n for n in all_news
        if sym.lower() in n["title"].lower()
        or sym in n.get("tokens", [])
    ]
    return sorted(relevant, key=lambda x: abs(x["sentiment_score"]), reverse=True)[:limit]


def get_market_sentiment() -> dict:
    """Aggregate market-wide sentiment from all news."""
    news = fetch_all_news()
    if not news:
        return {"score": 0, "count": 0, "direction": "neutral"}
    avg = sum(n["sentiment_score"] for n in news) / len(news)
    direction = "bullish" if avg > 15 else "bearish" if avg < -15 else "neutral"
    return {"score": int(avg), "count": len(news), "direction": direction}


def refresh_news():
    """Called by scheduler to pre-warm cache."""
    fetch_all_news()
    log.info("News aggregator refreshed: %d items", len(_cache.get("cryptopanic", (0, []))[1]))
