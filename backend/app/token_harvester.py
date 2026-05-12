"""Token Harvester — SosoValue-first token discovery, CoinGecko fallback only.

Priority: SosoValue sectors/indices → DexScreener prices → CoinGecko (charts only).
"""

import logging
import time

logger = logging.getLogger(__name__)


def harvest_from_sosovalue(limit: int = 50) -> list[dict]:
    """Primary: fetch tokens from SosoValue sectors + index constituents."""
    from app.sosovalue_client import (
        get_sector_tokens, get_currency_snapshots_batch,
        _is_enabled, _rate_limit_remaining,
    )
    if not _is_enabled() or _rate_limit_remaining() < 3:
        return []
    try:
        tokens = get_sector_tokens(limit)
        # Enrich top tokens with per-token snapshots
        if tokens and _rate_limit_remaining() > 5:
            top_ids = [t["coingecko_id"] for t in tokens[:10] if t.get("coingecko_id")]
            snapshots = get_currency_snapshots_batch(top_ids, max_n=8)
            for t in tokens[:10]:
                snap = snapshots.get(t.get("coingecko_id", ""))
                if snap:
                    t["price"] = float(snap.get("price", t["price"]) or t["price"])
                    t["market_cap"] = float(snap.get("marketCap", t["market_cap"]) or t["market_cap"])
                    t["volume_24h"] = float(snap.get("volume24h", t["volume_24h"]) or t["volume_24h"])
                    t["source"] = "sosovalue_enriched"
        return tokens
    except Exception as e:
        logger.warning("SoSoValue harvest failed: %s", e)
        return []


def harvest_from_coingecko(limit: int = 100) -> list[dict]:
    """Fallback only: single CoinGecko call with per_page=100."""
    import httpx
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "volume_desc",
                    "per_page": min(limit, 100), "page": 1,
                    "sparkline": False, "price_change_percentage": "1h,24h"},
            timeout=15,
        )
        resp.raise_for_status()
        tokens = []
        for c in resp.json():
            tokens.append({
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
                "source": "coingecko",
            })
        return tokens
    except Exception as e:
        logger.warning("CoinGecko harvest failed: %s", e)
        return []


def _merge_tokens(primary: list[dict], fallback: list[dict]) -> list[dict]:
    """Deduplicate by symbol, prefer primary (SosoValue) data."""
    by_symbol: dict[str, dict] = {}
    for t in fallback:
        by_symbol[t["token_symbol"]] = t
    for t in primary:
        sym = t.get("token_symbol", "")
        if sym in by_symbol:
            by_symbol[sym].update({k: v for k, v in t.items() if v})
            by_symbol[sym]["source"] = "sosovalue+coingecko"
        else:
            by_symbol[sym] = t
    return list(by_symbol.values())


def _score_interest(tokens: list[dict]) -> list[dict]:
    """Score tokens by interestingness for card generation."""
    for t in tokens:
        score = 0
        vol_mcap = t["volume_24h"] / max(t.get("market_cap", 1), 1)
        if vol_mcap > 0.3:
            score += 30
        if abs(t.get("price_change_1h") or 0) > 5:
            score += 25
        if abs(t.get("price_change_24h") or 0) > 10:
            score += 20
        if t.get("sector"):
            score += 10  # SosoValue sector membership bonus
        t["interest_score"] = score
    tokens.sort(key=lambda t: t.get("interest_score", 0), reverse=True)
    return tokens


def harvest_all(limit: int = 60) -> list[dict]:
    """SosoValue-first harvest. CoinGecko only as fallback when SosoValue < 20 tokens."""
    sv_tokens = harvest_from_sosovalue(limit)

    if len(sv_tokens) >= 20:
        # SosoValue sufficient — skip CoinGecko bulk call entirely
        logger.info("SosoValue-first: %d tokens (no CoinGecko needed)", len(sv_tokens))
        return _score_interest(sv_tokens)[:limit]

    # Fallback: single CoinGecko call
    cg_tokens = harvest_from_coingecko(limit)
    merged = _merge_tokens(sv_tokens, cg_tokens)
    logger.info("Harvest: %d SosoValue + %d CoinGecko → %d merged", len(sv_tokens), len(cg_tokens), len(merged))
    return _score_interest(merged)[:limit]
