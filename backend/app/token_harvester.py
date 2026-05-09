"""Token Harvester — unified multi-source token universe."""
import logging
import time

logger = logging.getLogger(__name__)


def harvest_from_coingecko(limit: int = 100) -> list[dict]:
    """Fetch tokens from CoinGecko (extracted from content_engine)."""
    from app.content_engine import harvest_tokens
    return harvest_tokens(limit)


def harvest_from_sosovalue() -> list[dict]:
    """Fetch tokens from hot sectors via SoSoValue."""
    from app.sosovalue_client import get_sector_tokens, _is_enabled, _rate_limit_remaining
    if not _is_enabled() or _rate_limit_remaining() < 3:
        return []
    try:
        return get_sector_tokens(limit=30)
    except Exception as e:
        logger.warning(f"SoSoValue harvest failed: {e}")
        return []


def _merge_tokens(cg_tokens: list[dict], sv_tokens: list[dict]) -> list[dict]:
    """Deduplicate by symbol, prefer SoSoValue enrichment."""
    by_symbol: dict[str, dict] = {}
    for t in cg_tokens:
        by_symbol[t["token_symbol"]] = t
    for t in sv_tokens:
        sym = t.get("token_symbol", "")
        if sym in by_symbol:
            by_symbol[sym].update({k: v for k, v in t.items() if v and k not in ("price", "market_cap", "volume_24h")})
            by_symbol[sym]["source"] = "sosovalue+coingecko"
        else:
            t["source"] = "sosovalue"
            by_symbol[sym] = t
    return list(by_symbol.values())


def harvest_all(limit: int = 60) -> list[dict]:
    """Merge CoinGecko + SoSoValue into deduplicated, scored token list."""
    cg = harvest_from_coingecko(limit)
    sv = harvest_from_sosovalue()
    merged = _merge_tokens(cg, sv)
    merged.sort(key=lambda t: t.get("interest_score", 0), reverse=True)
    return merged[:limit]
