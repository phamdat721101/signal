"""lp_math.py — pure math for concentrated-LP quotes.

Single Responsibility: given a Token-A amount and a price band, derive the
matching Token-B amount, the user's pool share, and a 24h fee projection.
No I/O, no DB, no config — just `math`.

Uniswap-V3 reference: https://docs.uniswap.org/concepts/protocol/concentrated-liquidity
We use the closed-form expressions for (amount0, amount1) given liquidity L:

    amount0 = L · (√Pᵤ − √P)  / (√P · √Pᵤ)        when P_curr ∈ [P_l, P_u]
    amount1 = L · (√P  − √P_l)

Solve for `amount1` from `amount0` (Token-A first). Edge cases:
  • current price ≤ lower → user is fully in Token-B (amount0 = 0)
  • current price ≥ upper → user is fully in Token-A (amount1 = 0)
"""
from __future__ import annotations

import math
from typing import NamedTuple


class LpQuote(NamedTuple):
    token_b_amount: float        # in Token-B units
    pool_share_pct: float        # of pool TVL after deposit
    est_fee_24h_usd: float       # rough projection (USD)
    user_tvl_usd: float


def derive_token_b(amount_a: float, p_curr: float, p_low: float, p_high: float) -> float:
    """Token-B that pairs with `amount_a` of Token-A across [p_low, p_high]."""
    if amount_a <= 0 or p_curr <= 0 or p_low <= 0 or p_high <= p_low:
        return 0.0
    s_curr = math.sqrt(p_curr)
    s_low = math.sqrt(p_low)
    s_high = math.sqrt(p_high)

    # Current price below range → 100% Token-A; no Token-B needed.
    if p_curr <= p_low:
        return 0.0
    # Current price above range → 100% Token-B; can't deposit Token-A.
    if p_curr >= p_high:
        # Caller should treat this as "out-of-range, swap first or pick a wider band".
        # Returning 0 keeps the API total-deposit-friendly.
        return 0.0

    # In-range: solve L from amount0, then back out amount1.
    # amount_a = L · (√Pᵤ − √P) / (√P · √Pᵤ)
    # ⇒ L = amount_a · √P · √Pᵤ / (√Pᵤ − √P)
    denom = s_high - s_curr
    if denom <= 0:
        return 0.0
    liquidity = amount_a * s_curr * s_high / denom
    return liquidity * (s_curr - s_low)


def quote(
    *,
    amount_a: float,
    p_curr: float,
    p_low: float,
    p_high: float,
    pool_tvl_usd: float,
    apy: float,
    token_a_usd: float,
    token_b_usd: float,
) -> LpQuote:
    """Combine derive_token_b with TVL/fee projections into a single LpQuote."""
    amount_b = derive_token_b(amount_a, p_curr, p_low, p_high)
    user_tvl = amount_a * token_a_usd + amount_b * token_b_usd
    new_pool_tvl = max(pool_tvl_usd + user_tvl, 1.0)
    pool_share = user_tvl / new_pool_tvl
    # Concentrated LPs earn fees only when price stays in range.
    # Naïve projection: fees = TVL_user × (APY/365). Multiply by 0.7 to hint
    # at less-than-100% in-range time; keeps the number honest without a
    # full Monte-Carlo.
    fee_24h_usd = user_tvl * (apy / 100.0) / 365.0 * 0.7
    return LpQuote(
        token_b_amount=amount_b,
        pool_share_pct=pool_share * 100.0,
        est_fee_24h_usd=fee_24h_usd,
        user_tvl_usd=user_tvl,
    )


# ── Range-band presets (k · σ_daily) ──────────────────────────────────
# Same constants are exposed to FE via cardModes-style export; backend
# owns the canonical values so the quote endpoint and the FE preview
# never diverge.
PRESETS: dict[str, float] = {
    "conservative": 2.0,
    "balanced":     1.0,
    "aggressive":   0.5,
}

# Fixed-band fallback (used when σ_7d is unavailable). Returns (min, max) %.
FIXED_BANDS: dict[str, tuple[float, float]] = {
    "conservative": (0.85, 1.15),
    "balanced":     (0.93, 1.07),
    "aggressive":   (0.97, 1.03),
}


def range_for_preset(p_curr: float, sigma_7d: float | None, preset: str) -> tuple[float, float]:
    """[P·(1 − k·σ), P·(1 + k·σ)] with fallback to fixed bands."""
    preset = preset.lower()
    if preset not in PRESETS:
        preset = "balanced"
    if sigma_7d and sigma_7d > 0:
        k = PRESETS[preset]
        # Clamp σ to a sane range so a degenerate σ doesn't produce a
        # zero-width or 1000% band. Anything > 50% daily is suspicious;
        # cap at 50% so the k·σ term stays bounded.
        s = min(sigma_7d, 0.5)
        return p_curr * (1 - k * s), p_curr * (1 + k * s)
    lo, hi = FIXED_BANDS[preset]
    return p_curr * lo, p_curr * hi
