"""volatility.py — 7-day price-volatility helper for LP range suggestions.

Single Responsibility: given a token symbol, return the daily-σ estimate of
log-returns over the last 7 days. Used by `lp_advisory.py` (precompute) and by
`/api/cards/{id}/lp-recipe` (just-in-time fallback) to size concentrated-LP
ranges via `[P·(1 − k·σ), P·(1 + k·σ)]`.

Design choices:
  • CoinGecko market_chart is the data source — same source `signal_engine.py`
    already uses for "1h candles / 7d horizon", so no new third-party
    dependency. We pull at hourly granularity via `days=7` (CoinGecko returns
    ~hourly points for 2-90 day windows).
  • Returns DAILY σ (not annualized). The downstream range formula is
    `P·(1 ± k·σ)` and the user picks k ∈ {2.0, 1.0, 0.5}. Keeping σ in the
    same time scale as the holding period means k is read intuitively as
    "stdev units of a single-day move".
  • Routes through `http_client.get` so the project-wide CircuitBreaker +
    retry policy applies (per product_context.md §4).
  • In-process 30-min TTL cache. Per-worker; promote to Redis only when ≥3
    modules share it (project rule).
  • Returns `None` on any failure → caller falls back to fixed-% bands.
"""
from __future__ import annotations

import math
import time
from typing import Optional

from app import http_client

# {symbol_upper: (timestamp, sigma_daily)}
_cache: dict[str, tuple[float, Optional[float]]] = {}
_TTL_SECONDS = 1800  # 30 min

# Best-effort symbol→CoinGecko-id map. Extend on demand. Unknown symbols
# return None → fixed-band fallback. We deliberately keep this tiny rather
# than importing a 10k-row table; matches the philosophy of the existing
# tracked-asset placeholders in `chain_ops.py`.
_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "USDC": "usd-coin", "USDT": "tether", "DAI": "dai",
    "OKB": "okb", "INIT": "initia", "BNB": "binancecoin",
    "MATIC": "matic-network", "AVAX": "avalanche-2",
    "ARB": "arbitrum", "OP": "optimism", "LINK": "chainlink",
    "ATOM": "cosmos", "INJ": "injective-protocol",
}


def _coingecko_id(symbol: str) -> Optional[str]:
    return _COINGECKO_IDS.get(symbol.upper())


def _fetch_prices(cg_id: str) -> Optional[list[float]]:
    """Pull `prices` array from CoinGecko market_chart. Returns prices only."""
    resp = http_client.get(
        f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart",
        service="coingecko",
        params={"vs_currency": "usd", "days": "7", "interval": "hourly"},
    )
    if resp is None or resp.status_code != 200:
        return None
    try:
        return [float(p[1]) for p in resp.json().get("prices", []) if p and p[1]]
    except (ValueError, TypeError, KeyError):
        return None


def _stdev_log_returns_daily(prices: list[float]) -> Optional[float]:
    """Daily σ from hourly prices: stdev(log returns) × √(24)."""
    if len(prices) < 24:  # need at least one full day to be meaningful
        return None
    rets = [
        math.log(prices[i] / prices[i - 1])
        for i in range(1, len(prices))
        if prices[i - 1] > 0 and prices[i] > 0
    ]
    if len(rets) < 12:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    hourly_sigma = math.sqrt(var)
    return hourly_sigma * math.sqrt(24)  # hourly → daily


def compute_sigma_7d(symbol: str) -> Optional[float]:
    """Daily-σ of log-returns over the last 7 days. None on missing data."""
    if not symbol:
        return None
    key = symbol.upper()
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]

    cg_id = _coingecko_id(symbol)
    if not cg_id:
        _cache[key] = (now, None)
        return None

    prices = _fetch_prices(cg_id)
    sigma = _stdev_log_returns_daily(prices) if prices else None
    _cache[key] = (now, sigma)
    return sigma
