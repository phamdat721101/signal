"""LP Advisory Engine — generates position recommendations from DeFiLlama pools.

Single Responsibility: turn raw DeFiLlama pool dicts into `card_type='pool'`
rows enriched with the metadata the FE Configurator + agent API need
(token0/1 addresses + symbols + decimals, pool address, chain id, dex link,
7d volatility). The card-row writer is `db.insert_card`; this module only
shapes the payload.
"""
from __future__ import annotations

import logging
from typing import Any

from app import db
from app.content_engine import _fetch_llama_pools
from app.dex_links import _CHAIN_ID, build_dex_link
from app.volatility import compute_sigma_7d

logger = logging.getLogger(__name__)

# Decimals lookup for tokens whose decimals != 18 (the EVM default).
# Extend on demand. Anything not listed defaults to 18.
_KNOWN_DECIMALS: dict[str, int] = {
    "USDC": 6, "USDT": 6, "USDC.E": 6, "USDBC": 6,
    "WBTC": 8, "BTCB": 8, "TBTC": 8,
}


def _decimals_for(symbol: str | None) -> int:
    if not symbol:
        return 18
    return _KNOWN_DECIMALS.get(symbol.upper(), 18)


def _split_pair(symbol: str) -> tuple[str, str]:
    """`ETH-USDC` or `ETH/USDC` → (`ETH`, `USDC`). Falls back to (sym, '')."""
    for sep in ("-", "/", " "):
        if sep in symbol:
            a, b = symbol.split(sep, 1)
            return a.strip().upper(), b.strip().upper()
    return symbol.strip().upper(), ""


def pool_enrichment(p: dict) -> dict[str, Any]:
    """Return the LP-specific fields to merge into a card payload.

    Pure: no DB writes, no exceptions on missing data — every field is
    nullable downstream. Network calls are limited to `compute_sigma_7d`
    (cached + circuit-broken via http_client).
    """
    tokens = p.get("underlyingTokens") or []
    token0_addr = tokens[0] if len(tokens) >= 1 else None
    token1_addr = tokens[1] if len(tokens) >= 2 else None

    sym0, sym1 = _split_pair(p.get("symbol", "") or "")
    chain_id = _CHAIN_ID.get((p.get("chain") or "").lower())

    # σ_7d on the primary (volatile) leg. For most pools that's token0; for
    # USDC-* pools the volatile leg may be token1 — use whichever has a
    # known CoinGecko id.
    sigma = compute_sigma_7d(sym0) or compute_sigma_7d(sym1)

    return {
        "token0_address": (token0_addr or "").lower() or None,
        "token1_address": (token1_addr or "").lower() or None,
        "token0_symbol": sym0 or None,
        "token1_symbol": sym1 or None,
        "token0_decimals": _decimals_for(sym0),
        "token1_decimals": _decimals_for(sym1),
        "pool_address": p.get("pool"),
        "chain_id": chain_id,
        "dex_link": build_dex_link(p),
        "volatility_7d_sigma": sigma,
    }


# ────────────────────────────────────────────────────────────────────
#  Advisory action heuristic — kept separate from enrichment for SRP.
# ────────────────────────────────────────────────────────────────────

def _compute_action(pool: dict) -> tuple[str, int, str]:
    """Determine ENTER/EXIT/HOLD with confidence and reasoning."""
    apy = pool.get("apy", 0)
    il = abs(pool.get("il7d") or 0)
    fee_apr = pool.get("apyBase") or 0

    if apy > 15 and il < 1:
        confidence = min(85, 50 + int(apy / 2))
        return "ENTER", confidence, f"High APY ({apy:.1f}%) with minimal IL ({il:.2f}%). Fee income dominates."
    if il > fee_apr and il > 2:
        confidence = min(80, 40 + int(il * 5))
        return "EXIT", confidence, f"IL ({il:.2f}%) exceeds fee income ({fee_apr:.1f}%). Position losing value."
    confidence = max(30, 50 - int(il * 10))
    return "HOLD", confidence, f"Moderate APY ({apy:.1f}%) with manageable IL ({il:.2f}%). Monitor closely."


def generate_lp_advisories(limit: int = 5) -> list[dict]:
    """Produce LP advisory decisions and store them as enriched pool cards."""
    try:
        pools = _fetch_llama_pools()
        if not pools:
            return []
        out: list[dict] = []
        for p in pools[:limit]:
            action, confidence, reasoning = _compute_action(p)
            apy = round(p.get("apy", 0), 2)
            il_score = min(100, int(abs(p.get("il7d") or 0) * 20))
            payload = {
                "token_symbol": p.get("symbol", "???"),
                "token_name": f"{p.get('project','unknown')} LP",
                "chain": p.get("chain", "unknown"),
                "hook": f"{action}: {reasoning[:80]}",
                "roast": "",
                "verdict": action,
                "verdict_reason": reasoning,
                "risk_score": il_score,
                "price": apy,
                "card_type": "pool",
                "source": "lp_advisory",
                **pool_enrichment(p),
            }
            db.insert_card(payload)
            out.append({
                "pool_id": p.get("pool", ""),
                "dex": p.get("project", "unknown"),
                "chain": p.get("chain", "unknown"),
                "token_pair": p.get("symbol", "???"),
                "action": action,
                "confidence": confidence,
                "expected_apr": apy,
                "il_risk_score": il_score,
                "reasoning": reasoning,
            })
        logger.info(f"Generated {len(out)} LP advisories")
        return out
    except Exception as e:
        logger.error(f"LP advisory generation failed: {e}")
        return []
