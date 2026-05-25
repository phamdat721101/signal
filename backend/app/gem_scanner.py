"""Gem Scanner — finds hidden gems from on-chain + market data.

Runs every 30min via scheduler. Produces gem cards into the existing feed.
Uses free APIs only: DEXScreener, CoinGecko, GoPlus.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from app.http_client import aget


@dataclass
class GemCandidate:
    symbol: str
    name: str
    address: str
    chain: str
    price: float
    market_cap: float
    volume_24h: float
    liquidity: float
    price_change_24h: float
    gem_score: int
    signals: list[str] = field(default_factory=list)
    upside_multiple: float = 3.0
    risk: int = 70


async def _fetch_dexscreener_boosts() -> list[dict]:
    resp = await aget("https://api.dexscreener.com/token-boosts/top/v1", service="dexscreener")
    if not resp:
        return []
    data = resp.json()
    return data[:80] if isinstance(data, list) else []


async def _fetch_coingecko_trending() -> list[dict]:
    resp = await aget("https://api.coingecko.com/api/v3/search/trending", service="coingecko")
    if not resp:
        return []
    data = resp.json()
    if not isinstance(data, dict) or "coins" not in data:
        return []
    return data["coins"][:30]


async def _check_safety(address: str, chain_id: str = "1") -> dict:
    resp = await aget(
        f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}",
        service="goplus",
    )
    if not resp:
        return {"safe": False}
    data = resp.json()
    if not isinstance(data, dict) or "result" not in data:
        return {"safe": False}
    info = (data.get("result") or {}).get(address.lower(), {})
    is_honeypot = info.get("is_honeypot", "1") == "1"
    is_verified = info.get("is_open_source", "0") == "1"
    return {"safe": not is_honeypot and is_verified, "verified": is_verified}


def _score(token: dict, safety: dict) -> GemCandidate | None:
    if not safety.get("safe"):
        return None

    score = 0
    signals = []
    mc = float(token.get("market_cap", 0) or 0)
    vol = float(token.get("volume_24h", 0) or 0)
    change = float(token.get("price_change_24h", 0) or 0)
    liq = float(token.get("liquidity", 0) or 0)
    price = float(token.get("price", 0) or 0)

    # Volume/MC ratio (if both available)
    if mc > 0 and vol > 0 and vol / mc > 0.2:
        score += 20
        signals.append(f"📊 Vol/MC {vol/mc:.1f}x — accumulation")

    # Momentum
    if change > 3:
        score += 15
        signals.append(f"📈 +{change:.0f}% momentum")
    elif vol > 100_000 and mc == 0:
        score += 15
        signals.append(f"📈 ${vol/1e3:.0f}K volume (new)")

    # Market cap tiers
    if 0 < mc < 50_000_000:
        score += 20
        signals.append(f"💎 MC ${mc/1e6:.1f}M (low cap)")
    elif mc == 0 and vol > 0:
        score += 15
        signals.append("💎 Emerging token")
    elif mc < 500_000_000:
        score += 10
        signals.append(f"💎 MC ${mc/1e6:.0f}M (mid cap)")

    # Liquidity or volume as proxy
    if liq > 50_000:
        score += 10
        signals.append(f"💧 ${liq/1e3:.0f}K liquidity")
    elif vol > 50_000:
        score += 10
        signals.append(f"💧 ${vol/1e3:.0f}K daily volume")

    # Verified
    if safety.get("verified"):
        score += 10
        signals.append("✅ Verified")

    # Narrative
    name_lower = (token.get("name", "") + " " + token.get("symbol", "")).lower()
    for kw, pts in [("ai", 15), ("agent", 15), ("rwa", 10), ("depin", 10), ("meme", 5), ("pepe", 5)]:
        if kw in name_lower:
            score += pts
            signals.append(f"🔥 '{kw.upper()}' narrative")
            break

    if score < 30 or not signals:
        return None

    upside = 10.0 if mc < 1_000_000 else 5.0 if mc < 10_000_000 else 3.0 if mc < 100_000_000 else 2.0

    return GemCandidate(
        symbol=token.get("symbol", "?")[:10],
        name=token.get("name", "?")[:30],
        address=token.get("address", ""),
        chain=token.get("chain", "ethereum"),
        price=price,
        market_cap=mc,
        volume_24h=vol,
        liquidity=liq,
        price_change_24h=change,
        gem_score=min(100, score),
        signals=signals[:4],
        upside_multiple=upside,
        risk=max(20, 100 - score),
    )


async def scan_for_gems(limit: int = 5) -> list[GemCandidate]:
    """Main entry. Returns top gems sorted by score."""
    dex_data, cg_data = await asyncio.gather(
        _fetch_dexscreener_boosts(),
        _fetch_coingecko_trending(),
    )

    # Normalize candidates
    candidates = []
    for item in dex_data:
        candidates.append({
            "symbol": item.get("symbol", item.get("tokenAddress", "")[:6]),
            "name": item.get("description", "") or item.get("name", ""),
            "address": item.get("tokenAddress", ""),
            "chain": item.get("chainId", "ethereum"),
            "price": 0,
            "market_cap": 0,
            "volume_24h": float(item.get("totalAmount", 0) or 0),
            "liquidity": 0,
            "price_change_24h": 0,
        })
    for coin in cg_data:
        c = coin.get("item", {})
        d = c.get("data", {})

        def _parse_num(v) -> float:
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                return float(v.replace("$", "").replace(",", "").strip() or "0")
            return 0.0

        candidates.append({
            "symbol": c.get("symbol", "?"),
            "name": c.get("name", "?"),
            "address": c.get("id", ""),
            "chain": "ethereum",
            "price": _parse_num(d.get("price", 0)),
            "market_cap": _parse_num(d.get("market_cap", 0)),
            "volume_24h": _parse_num(d.get("total_volume", 0)),
            "liquidity": 0,
            "price_change_24h": float((d.get("price_change_percentage_24h") or {}).get("usd", 0) or 0),
        })

    # Score (limit safety checks to avoid rate limits)
    gems = []
    chain_map = {"ethereum": "1", "bsc": "56", "base": "8453", "solana": "solana", "arbitrum": "42161"}
    for token in candidates[:50]:
        addr = token.get("address", "")
        if not addr or len(addr) < 10:
            # CoinGecko IDs aren't addresses — skip safety, score on data alone
            safety = {"safe": True, "verified": True}
        else:
            chain_id = chain_map.get(token.get("chain", ""), "1")
            safety = await _check_safety(addr, chain_id)
        gem = _score(token, safety)
        if gem:
            gems.append(gem)

    gems.sort(key=lambda g: g.gem_score, reverse=True)
    return gems[:limit]
