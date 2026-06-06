"""sodex_links.py — pure URL/payload builder for SoDex trade verification.

Single Responsibility: turn a `(symbol, kind, order_id?)` tuple into the
canonical SoDex web URLs (pair · portfolio · explorer) and, when an
order id is supplied, the full link payload including the live fills
list.

SOLID:
  - SRP: one job, no I/O for the URL pieces, side-effect-only when fills
    are requested.
  - OCP: adding a new link kind = adding one row to `_KIND_PATHS`.
  - DIP: the fills fetcher is injected (defaults to `sodex_client`) so
    tests don't need network access.

URL truth table
---------------
SoDex web app URLs (verified 2026-06-06 via sodex.com nav):
  pair (perps): https://sodex.com/trade/futures/{BASE}_USDC
  pair (spot):  https://sodex.com/trade/spot/{BASE}_USDC
  portfolio:    https://sodex.com/portfolio          (login-gated, per-user)
  explorer:     https://sodex.com/explorer?blocktype={futures|spot}

Why no per-order URL: SoDex doesn't document a stable
`?orderID=` deep-link pattern today. We surface the safer triplet
(pair, portfolio, explorer) plus the live fills list — which is the
authoritative proof anyway.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

_BASE = "https://sodex.com"

# `kind` → (web path prefix, explorer blocktype query value)
_KIND_PATHS: dict[str, tuple[str, str]] = {
    "perps": ("trade/futures", "futures"),
    "spot":  ("trade/spot",    "spot"),
}

# Tradeable assets default-quoted in vUSDC on testnet, USDC on mainnet.
# Pair label format on sodex.com is `{BASE}_{QUOTE}` (underscore).
_DEFAULT_QUOTE = "USDC"


def _normalize_symbol(symbol: str) -> str:
    """`BTC` / `BTC/USD` / `BTC-USD` / `vBTC_vUSDC` → `BTC_USDC`."""
    if not symbol:
        return ""
    # Strip the "v" testnet prefix and split on common separators.
    s = symbol.upper().strip().lstrip("V")
    for sep in ("/", "-", "_"):
        if sep in s:
            base = s.split(sep, 1)[0].lstrip("V")
            return f"{base}_{_DEFAULT_QUOTE}"
    return f"{s}_{_DEFAULT_QUOTE}"


def symbol_url(symbol: str, kind: str = "perps") -> str:
    """SoDex pair page URL. Falls back to perps for unknown kinds."""
    path, _ = _KIND_PATHS.get(kind, _KIND_PATHS["perps"])
    return f"{_BASE}/{path}/{_normalize_symbol(symbol)}"


def portfolio_url() -> str:
    """User's SoDex portfolio (login-gated; their own positions+fills)."""
    return f"{_BASE}/portfolio"


def explorer_url(kind: str = "perps") -> str:
    """ValueChain native explorer scoped to the trade kind."""
    _, blocktype = _KIND_PATHS.get(kind, _KIND_PATHS["perps"])
    return f"{_BASE}/explorer?blocktype={blocktype}"


def build_links(symbol: str, kind: str = "perps") -> dict[str, str]:
    """Symbol-only payload — used for live position rows that have no
    discrete order id (Portfolio "Live SoDex Positions" panel).
    """
    return {
        "symbol_url": symbol_url(symbol, kind),
        "portfolio_url": portfolio_url(),
        "explorer_url": explorer_url(kind),
    }


# ── Composite payload (with fills) ──────────────────────────────────────
# The fills fetcher is injected; default is the real `sodex_client` call.
# Tests substitute a stub. Returns [] on any failure (graceful degrade).
FillsFetcher = Callable[[int], list[dict[str, Any]]]


def _default_fills_fetcher(order_id: int) -> list[dict[str, Any]]:
    try:
        from app.sodex_client import get_sodex_client
        client = get_sodex_client()
        if client is None:
            return []
        return client.fetch_fills_for_order(order_id) or []
    except Exception:
        return []


def build_links_payload(
    trade_row: dict[str, Any],
    *,
    fills_fetcher: Optional[FillsFetcher] = None,
) -> dict[str, Any]:
    """Full link + fills payload for a `trades` row.

    Required keys on `trade_row`: `token_symbol`, `execution_type`,
    `sodex_order_id` (nullable). Returns a dict ready for JSON response.

    `kind` always defaults to `perps` — Kinetic only generates perps-style
    predictions today. Paper trades still get a perps pair URL so the
    user can see the same market they predicted on.
    """
    symbol = str(trade_row.get("token_symbol") or "")
    is_sodex_perps = (trade_row.get("execution_type") == "sodex_perps")
    kind = "perps"

    payload: dict[str, Any] = build_links(symbol, kind)
    payload["fills"] = []

    order_id = trade_row.get("sodex_order_id")
    if is_sodex_perps and order_id:
        try:
            fetcher = fills_fetcher or _default_fills_fetcher
            payload["fills"] = fetcher(int(order_id))
        except Exception:
            payload["fills"] = []
    return payload
