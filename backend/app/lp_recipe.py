"""lp_recipe.py — recipe orchestration for the LP Configurator.

Single Responsibility: given a pool card + Token-A amount + preset, produce
the full payload the FE Configurator (and the paid agent API) need:

    {
        preset, sigma_7d,
        min_price, max_price,
        ticks: [lower, upper],
        amount_a, token_b_amount, pool_share_pct, est_fee_24h_usd,
        supported, dex_link,
    }

Why this lives in its own module: it stitches together pure math (`lp_math`),
chain-specific helpers (`xlayer`), and I/O (`price_feed`, `volatility`).
Keeping pure modules pure makes them trivially testable; this one is the
glue layer. Both `main.py` and `agent_api.py` import a single function.
"""
from __future__ import annotations

from typing import Any

from app import lp_math, xlayer
from app.price_feed import get_price
from app.volatility import compute_sigma_7d


def _spot_usd(symbol: str | None) -> float:
    if not symbol:
        return 0.0
    p = get_price(symbol)
    if not p:
        return 0.0
    return float(p.get("price_usd") or 0.0)


def build_recipe(card: dict[str, Any], *, amount_a: float, preset: str) -> dict[str, Any]:
    """Assemble the full LP recipe payload. Pure-ish (only fan-out is price_feed)."""
    if (card.get("card_type") or "") != "pool":
        raise ValueError(f"card {card.get('id')} is not a pool card")

    sym0 = (card.get("token0_symbol") or "").upper()
    sym1 = (card.get("token1_symbol") or "").upper()
    addr0 = card.get("token0_address")
    addr1 = card.get("token1_address")
    chain_id = card.get("chain_id")

    # Spot prices: σ-derived band lives in token0/token1 ratio space.
    p0_usd = _spot_usd(sym0)
    p1_usd = _spot_usd(sym1) or 1.0  # USDC pools default token1=USDC=$1
    p_curr = (p0_usd / p1_usd) if p1_usd > 0 else 0.0

    # σ_7d — prefer the row's stored value; fall back to live compute.
    sigma = card.get("volatility_7d_sigma")
    if sigma is None or sigma <= 0:
        sigma = compute_sigma_7d(sym0) or compute_sigma_7d(sym1)

    # Price band → ticks + Token-B derivation. If we have no spot price the
    # math collapses; return a sentinel recipe rather than 500.
    if p_curr <= 0:
        return {
            "preset": preset,
            "sigma_7d": sigma,
            "min_price": None,
            "max_price": None,
            "ticks": None,
            "amount_a": amount_a,
            "token_b_amount": 0.0,
            "pool_share_pct": 0.0,
            "est_fee_24h_usd": 0.0,
            "supported": False,
            "dex_link": card.get("dex_link") or "",
            "reason": "no_spot_price",
        }

    p_low, p_high = lp_math.range_for_preset(p_curr, sigma, preset)
    try:
        ticks = list(xlayer.compute_range_ticks(p_low, p_high))
    except ValueError:
        ticks = None

    quote = lp_math.quote(
        amount_a=amount_a,
        p_curr=p_curr,
        p_low=p_low,
        p_high=p_high,
        pool_tvl_usd=float(card.get("market_cap") or 0.0),  # `market_cap` holds TVL for pool cards
        apy=float(card.get("price") or 0.0),               # `price` holds APY for pool cards
        token_a_usd=p0_usd,
        token_b_usd=p1_usd,
    )

    return {
        "preset": preset,
        "sigma_7d": sigma,
        "min_price": p_low,
        "max_price": p_high,
        "ticks": ticks,
        "amount_a": amount_a,
        "token_b_amount": quote.token_b_amount,
        "pool_share_pct": quote.pool_share_pct,
        "est_fee_24h_usd": quote.est_fee_24h_usd,
        "user_tvl_usd": quote.user_tvl_usd,
        "supported": xlayer.is_pair_supported(addr0, addr1, chain_id),
        "dex_link": card.get("dex_link") or "",
    }
