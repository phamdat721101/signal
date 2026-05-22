"""Morph Rails x402 — parallel payment rail to the Base/CDP path.

Single responsibility: build the Morph-flavored routes dict and a Morph-aware
x402ResourceServer. The CDP path in `x402_payment.py` is left untouched.

Why a separate module: Morph's facilitator requires HMAC-SHA256 over a
canonicalised request body, while CDP uses JWT bearer tokens. The x402-SDK's
`AuthProvider` protocol is body-blind (`get_auth_headers()` takes no body), so
we inject the HMAC at the httpx layer via an event hook on the AsyncClient
that the SDK consumes through `FacilitatorConfig.http_client`. This is the
Pythonic equivalent of Morph's documented Go `RoundTripper` pattern.

Reference: https://docs.morph.network/docs/morph-rails/agentic-payment/x402-facilitator
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
from x402.http import HTTPFacilitatorClient, FacilitatorConfig
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer
from x402.extensions.bazaar import (
    OutputConfig,
    bazaar_resource_server_extension,
    declare_discovery_extension,
)

from app.config import get_settings

log = logging.getLogger(__name__)


# ─── HMAC signer (pure function — easy to unit-test) ───────────────────
def _canonical_json(obj: Any) -> str:
    """Compact, lexicographically-sorted JSON. Matches Morph's spec exactly."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_morph_signature(
    *,
    access_key: str,
    secret_key: str,
    timestamp_ms: str,
    method: str,
    path: str,
    raw_query: str,
    raw_body: str,
) -> str:
    """Build the base64 HMAC-SHA256 signature per Morph x402 spec §3.

    `path` MUST include the `/x402` prefix (e.g. `/x402/v2/settle`).
    Query params are flattened to top-level `string[]` arrays in the sign map.
    Body is parsed into the sign map under `MORPH-ACCESS-BODY` when present.
    """
    sign_map: dict[str, Any] = {
        "MORPH-ACCESS-KEY": access_key,
        "MORPH-ACCESS-METHOD": method.upper(),
        "MORPH-ACCESS-PATH": path,
        "MORPH-ACCESS-TIMESTAMP": timestamp_ms,
    }
    if raw_query:
        for k, v in parse_qsl(raw_query, keep_blank_values=True):
            sign_map.setdefault(k, []).append(v)
    if raw_body:
        sign_map["MORPH-ACCESS-BODY"] = json.loads(raw_body)

    digest = hmac.new(secret_key.encode(), _canonical_json(sign_map).encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


# ─── httpx event hook — injects MORPH-ACCESS-* headers per request ─────
def _make_signing_hook(access_key: str, secret_key: str):
    async def _sign_request(request: httpx.Request) -> None:
        # /v2/supported is no-auth; spec §4.3
        if request.url.path.endswith("/v2/supported"):
            return
        body_bytes = request.content or b""
        raw_body = body_bytes.decode() if body_bytes else ""
        raw_query = request.url.query.decode() if isinstance(request.url.query, (bytes, bytearray)) else (request.url.query or "")
        ts_ms = str(int(time.time() * 1000))
        signature = compute_morph_signature(
            access_key=access_key,
            secret_key=secret_key,
            timestamp_ms=ts_ms,
            method=request.method,
            path=request.url.path,            # already includes /x402 prefix
            raw_query=raw_query,
            raw_body=raw_body,
        )
        request.headers["MORPH-ACCESS-KEY"] = access_key
        request.headers["MORPH-ACCESS-TIMESTAMP"] = ts_ms
        request.headers["MORPH-ACCESS-SIGN"] = signature
    return _sign_request


def _make_morph_client(access_key: str, secret_key: str, timeout: float = 15.0) -> httpx.AsyncClient:
    """Async httpx client that auto-signs every Morph facilitator request."""
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        event_hooks={"request": [_make_signing_hook(access_key, secret_key)]},
    )


# ─── Routes — mirror x402_payment.py shape, swap network/asset/payTo ───
_ROUTE_PRICES: dict[str, tuple[str, str, dict]] = {
    # path → (price, description, output_example)
    # Prices include AltFee narrative — gas paid in USDC, not ETH.
    "/api/v2/agent/decisions": (
        "$0.001",
        "AI crypto trading signals (60.8% accuracy across 5,816+ on-chain resolved predictions). APE/FADE/HOLD verdicts with confidence, entry, target, stop, reasoning, per-token track record. Settled on Morph Rails — pay gas in USDC via AltFee, no ETH required.",
        {"decisions": [{"token": "BTC", "action": "APE", "confidence": 85, "entry": 104250.5, "target": 105814.3, "stop": 102686.7, "track_record": {"win_rate": 68.5, "sample_size": 42}}], "total": 1},
    ),
    "/api/v2/agent/prices": (
        "$0.001",
        "Real-time aggregated cryptocurrency spot prices from CoinGecko + DexScreener with source attribution. Pass comma-separated symbols (e.g. BTC,ETH,SOL). Settled on Morph Rails.",
        {"prices": [{"symbol": "BTC", "price": 104250.5, "source": "coingecko"}]},
    ),
    "/api/v2/agent/pools": (
        "$0.005",
        "DeFi LP pool advisory ranked by APY and TVL with impermanent-loss risk scoring across multiple chains. Returns curated APE/FADE recommendations. Settled on Morph Rails.",
        {"pools": [{"pair": "ETH/USDC", "apy": 12.5, "tvl": 5000000, "risk_score": 35}], "total": 1},
    ),
    "/api/v2/agent/track-record": (
        "$0.01",
        "Historical prediction accuracy and per-token win rates from 5,816+ on-chain resolved predictions. Includes overall accuracy, per-token breakdown, sample size, and average PnL. Settled on Morph Rails.",
        {"overall": {"total": 5816, "wins": 3534, "win_rate": 60.8}, "per_token": {"BTC": {"total": 42, "wins": 29, "win_rate": 69.0, "avg_pnl": 1.42}}},
    ),
    "/api/v2/agent/context": (
        "$0.01",
        "Macro market context fused from SoSoValue institutional data: BTC/ETH ETF net flows, macro economic event calendar, sector rotation signals, breaking news, plus AI oracle market mood. Refreshed every 30s. Settled on Morph Rails.",
        {"sosovalue": {"etf_flows": {"btc_net_flow_24h": 150000000}}, "oracle_mood": "bullish"},
    ),
}


def _build_route(s, *, price: str, description: str, output_example: dict) -> RouteConfig:
    pay_to = s.morph_receiver_address or s.x402_receiver_address
    return RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=pay_to, price=price, network=s.morph_network)],
        mime_type="application/json",
        description=description,
        extensions=declare_discovery_extension(
            input={"limit": "10"},
            output=OutputConfig(example=output_example),
        ),
    )


# ─── Public factory — drop-in twin of get_x402_middleware_args() ──────
def get_morph_x402_middleware_args(prefix: str = "/morph-api") -> tuple[dict, x402ResourceServer] | tuple[None, None]:
    """Build (routes, server) for the Morph rail. Returns (None, None) if disabled
    or mis-configured — caller treats as "disabled, fail-open"."""
    s = get_settings()
    if not s.morph_x402_enabled:
        return (None, None)
    if not (s.morph_access_key and s.morph_access_secret):
        log.warning("Morph rail enabled but access key/secret missing — disabling")
        return (None, None)
    if not (s.morph_receiver_address or s.x402_receiver_address):
        log.warning("Morph rail enabled but no receiver address — disabling")
        return (None, None)

    try:
        facilitator = HTTPFacilitatorClient(FacilitatorConfig(
            url=s.morph_facilitator_url,
            http_client=_make_morph_client(s.morph_access_key, s.morph_access_secret),
        ))
        server = x402ResourceServer(facilitator)
        server.register(s.morph_network, ExactEvmServerScheme())
        server.register_extension(bazaar_resource_server_extension)
    except Exception as e:                           # noqa: BLE001 — fail-soft so Base path stays up
        log.warning("Morph facilitator init failed (rail disabled): %s", e)
        return (None, None)

    routes = {
        f"GET {prefix}{path}": _build_route(s, price=price, description=desc, output_example=ex)
        for path, (price, desc, ex) in _ROUTE_PRICES.items()
    }
    log.info("Morph rail ready: %d routes on %s -> %s", len(routes), s.morph_network, s.morph_facilitator_url)
    return (routes, server)
