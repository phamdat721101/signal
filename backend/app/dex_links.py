"""dex_links.py — deep-link templates for top-5 DEXes with DefiLlama fallback.

Single Responsibility: take a DefiLlama-shaped pool dict and produce a URL the
user can click to open the same pair on the source DEX. When the DEX isn't on
our known list, fall back to the DefiLlama pool page (always works).

Adding a new DEX: append one entry to `_TEMPLATES`. No code changes elsewhere.
DefiLlama project ids are lowercase, dash-separated (`uniswap-v3`,
`pancakeswap-amm-v3`). Source: https://api.llama.fi/protocols.
"""
from __future__ import annotations

from typing import Callable

# DefiLlama → numeric chain id (used by Uniswap "positions/create" linker).
_CHAIN_ID: dict[str, int] = {
    "ethereum": 1, "arbitrum": 42161, "optimism": 10,
    "base": 8453, "polygon": 137, "bsc": 56, "binance": 56,
    "avalanche": 43114, "celo": 42220, "blast": 81457,
    "zksync era": 324, "zksync": 324, "linea": 59144,
    "okx-x-layer": 196, "x layer": 196, "xlayer": 196,
}


def _addrs(pool: dict) -> tuple[str, str] | None:
    """Pull (token0, token1) addresses from DefiLlama's `underlyingTokens`."""
    tokens = pool.get("underlyingTokens") or []
    if len(tokens) < 2 or not all(tokens[:2]):
        return None
    return tokens[0], tokens[1]


def _uniswap_v3(pool: dict) -> str | None:
    addrs = _addrs(pool)
    if not addrs:
        return None
    chain_id = _CHAIN_ID.get((pool.get("chain") or "").lower())
    if not chain_id:
        return None
    a, b = addrs
    return (
        f"https://app.uniswap.org/positions/create/v3"
        f"?chain={chain_id}&currencyA={a}&currencyB={b}"
    )


def _pancake_v3(pool: dict) -> str | None:
    addrs = _addrs(pool)
    if not addrs:
        return None
    a, b = addrs
    return f"https://pancakeswap.finance/liquidity/add/{a}/{b}"


def _aerodrome(pool: dict) -> str | None:
    addrs = _addrs(pool)
    if not addrs:
        return None
    a, b = addrs
    return f"https://aerodrome.finance/deposit?token0={a}&token1={b}"


def _curve(pool: dict) -> str | None:
    pool_addr = pool.get("pool")
    if not pool_addr:
        return None
    return f"https://curve.fi/#/ethereum/pools/{pool_addr}/deposit"


def _balancer_v2(pool: dict) -> str | None:
    pool_id = pool.get("pool")
    if not pool_id:
        return None
    return f"https://app.balancer.fi/#/ethereum/pool/{pool_id}/add-liquidity"


_TEMPLATES: dict[str, Callable[[dict], str | None]] = {
    "uniswap-v3":          _uniswap_v3,
    "uniswap-v2":          _uniswap_v3,
    "pancakeswap-amm-v3":  _pancake_v3,
    "pancakeswap-amm":     _pancake_v3,
    "aerodrome-v1":        _aerodrome,
    "aerodrome-slipstream": _aerodrome,
    "curve-dex":           _curve,
    "balancer-v2":         _balancer_v2,
}


def _defillama_fallback(pool: dict) -> str:
    pool_id = pool.get("pool") or ""
    return f"https://defillama.com/yields/pool/{pool_id}"


def build_dex_link(pool: dict) -> str:
    """Return a clickable URL for the pool, falling back to DefiLlama."""
    project = (pool.get("project") or "").lower().strip()
    fn = _TEMPLATES.get(project)
    if fn:
        url = fn(pool)
        if url:
            return url
    return _defillama_fallback(pool)
