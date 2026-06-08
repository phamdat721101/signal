"""Somnia x402 rail — REST mirror for the on-chain SomniaAgentMarket.

Single responsibility: build the Somnia-flavored routes dict and an
x402ResourceServer pinned to `eip155:50312`. Off-chain agents that don't
yet speak Somnia EVM hit `/somnia-api/...`, receive a 402 challenge with a
Somnia-network payment requirement, and replay with a signed x-payment
header. Settlement is forwarded to a Somnia-aware facilitator (configurable;
defaults to the CDP facilitator URL — an alternative Somnia facilitator can
be plugged in via `SOMNIA_X402_FACILITATOR_URL`).

This rail is **purely additive**: it returns (None, None) when disabled so
that agent_main.py's existing Base rail remains byte-identical.
Mounted only when `SOMNIA_X402_ENABLED=true` AND a receiver address + asset
address are configured.
"""
from __future__ import annotations

import logging

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


# ─── Routes — mirror x402_payment.py shape; swap network/asset/payTo ───
# Pricing identical to other rails for parity. Descriptions emphasise the
# Somnia-native claim (validator-consensus AI signals) for Bazaar relevance.
_ROUTE_PRICES: dict[str, tuple[str, str, dict]] = {
    "/api/v2/agent/decisions": (
        "$0.001",
        "AI crypto trading signals with validator-consensus on the verdict (Somnia Agentic L1). "
        "60.8% accuracy across 5,816+ on-chain resolved predictions. APE/FADE verdicts with "
        "confidence, entry, target, stop, reasoning. Settled on Somnia testnet (chain 50312).",
        {"decisions": [{"token": "BTC", "action": "APE", "confidence": 85, "entry": 104250.5, "target": 105814.3, "stop": 102686.7}], "total": 1},
    ),
    "/api/v2/agent/prices": (
        "$0.001",
        "Real-time aggregated cryptocurrency prices. Settled on Somnia.",
        {"prices": [{"symbol": "BTC", "price": 104250.5, "source": "coingecko"}]},
    ),
    "/api/v2/agent/track-record": (
        "$0.01",
        "Historical prediction accuracy across 5,816+ on-chain resolved predictions. "
        "Includes per-token win rates and PnL. Settled on Somnia.",
        {"overall": {"total": 5816, "wins": 3534, "win_rate": 60.8}},
    ),
    "/api/v2/agent/context": (
        "$0.01",
        "Macro market context — ETF flows, sector rotation, oracle mood. Settled on Somnia.",
        {"oracle_mood": "bullish"},
    ),
}


def _build_route(s, *, price: str, description: str, output_example: dict) -> RouteConfig:
    pay_to = s.somnia_x402_receiver_address or s.x402_receiver_address
    return RouteConfig(
        accepts=[PaymentOption(
            scheme="exact",
            pay_to=pay_to,
            price=price,
            network=s.somnia_x402_network,
        )],
        mime_type="application/json",
        description=description,
        extensions=declare_discovery_extension(
            input={"limit": "10"},
            output=OutputConfig(example=output_example),
        ),
    )


# ─── Public factory — drop-in twin of get_x402_middleware_args() ──────
def get_somnia_x402_middleware_args(prefix: str = "/somnia-api") -> tuple[dict, x402ResourceServer] | tuple[None, None]:
    """Build (routes, server) for the Somnia rail. Returns (None, None) if disabled
    or mis-configured — caller treats as 'rail off, other rails untouched'."""
    s = get_settings()
    if not s.somnia_x402_enabled:
        return (None, None)
    if not (s.somnia_x402_receiver_address or s.x402_receiver_address):
        log.warning("Somnia rail enabled but no receiver address — disabling")
        return (None, None)

    try:
        facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=s.somnia_x402_facilitator_url))
        server = x402ResourceServer(facilitator)
        server.register(s.somnia_x402_network, ExactEvmServerScheme())
        server.register_extension(bazaar_resource_server_extension)
    except Exception as e:                           # noqa: BLE001 — fail-soft so other rails stay up
        log.warning("Somnia facilitator init failed (rail disabled): %s", e)
        return (None, None)

    routes = {
        f"GET {prefix}{path}": _build_route(s, price=price, description=desc, output_example=ex)
        for path, (price, desc, ex) in _ROUTE_PRICES.items()
    }
    log.info("Somnia rail ready: %d routes on %s -> %s", len(routes), s.somnia_x402_network, s.somnia_x402_facilitator_url)
    return (routes, server)
