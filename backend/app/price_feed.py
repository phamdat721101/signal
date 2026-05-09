"""Price Feed — multi-source price aggregator with DexScreener + CoinGecko."""
import logging
import time
import httpx

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, dict]] = {}
_DEXSCREENER_TTL = 10
_COINGECKO_TTL = 60


def _fetch_dexscreener(symbol: str) -> dict | None:
    """Fetch price from DexScreener (free, no key)."""
    try:
        resp = httpx.get(
            f"https://api.dexscreener.com/latest/dex/search?q={symbol}",
            timeout=10,
        )
        resp.raise_for_status()
        pairs = resp.json().get("pairs", [])
        if not pairs:
            return None
        pair = pairs[0]
        return {
            "symbol": symbol.upper(),
            "price_usd": float(pair.get("priceUsd", 0)),
            "source": "dexscreener",
            "timestamp": int(time.time()),
            "confidence": 0.95,
            "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
            "change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
        }
    except Exception as e:
        logger.warning(f"DexScreener fetch failed for {symbol}: {e}")
        return None


def _fetch_coingecko_price(symbol: str) -> dict | None:
    """Fetch price from CoinGecko simple/price."""
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": symbol.lower(), "vs_currencies": "usd",
                    "include_24hr_vol": "true", "include_24hr_change": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get(symbol.lower())
        if not data:
            return None
        return {
            "symbol": symbol.upper(),
            "price_usd": data.get("usd", 0),
            "source": "coingecko",
            "timestamp": int(time.time()),
            "confidence": 0.9,
            "volume_24h": data.get("usd_24h_vol", 0),
            "change_24h": data.get("usd_24h_change", 0),
        }
    except Exception as e:
        logger.warning(f"CoinGecko price fetch failed for {symbol}: {e}")
        return None


def get_price(symbol: str) -> dict | None:
    """Single token price lookup with cache + source priority."""
    now = time.time()
    cached = _cache.get(symbol.upper())
    if cached and now - cached[0] < _DEXSCREENER_TTL:
        return cached[1]
    result = _fetch_dexscreener(symbol)
    if not result:
        result = _fetch_coingecko_price(symbol)
    if not result and cached and now - cached[0] < 300:
        stale = cached[1].copy()
        stale["confidence"] = 0.3
        return stale
    if result:
        _cache[symbol.upper()] = (now, result)
    return result


def get_prices(symbols: list[str]) -> dict[str, dict]:
    """Get latest prices for multiple symbols."""
    return {s: p for s in symbols if (p := get_price(s))}
