"""GOAT testnet x402 rail — buyer-direct, verify-only paywall.

Single responsibility: gate `/goat-api/api/v2/agent/*` on goat-testnet3
(chainId 48816) by verifying an on-chain ERC-20 Transfer in a buyer-supplied
tx receipt. **No facilitator dependency** — CDP doesn't list GOAT and the
GOAT order API requires merchant credentials. Buyers sign + broadcast the
transfer themselves, then retry with `X-Payment-Tx: <hash>`.

This is the Python twin of `backend/agent-provider/src/paywall.ts` (which
already runs in production for Arbitrum Sepolia under the same logic).

Why a separate module from `x402_payment.py` and `somnia_payment.py`:
those rails delegate verify+settle to the `x402` Python SDK's
`x402ResourceServer`, which is hardwired to CDP-style facilitators. This
rail's protocol is different — challenge envelope only on the wire, no
facilitator round-trip — so trying to fit it through the SDK is more
fragile than mirroring the proven Node sidecar pattern in pure Python.

Token: configurable via env. Default WGBTC = `0xbC10…0000` (the gas-token
wrapper) since USDC is not yet issued on goat-testnet3. USD prices
(`$0.001`, `$0.005`, `$0.01`) are converted to token wei at boot using
the static env-configured `GOAT_X402_TOKEN_USD_PRICE` (Decision 4=a).

SOLID:
  • Single Responsibility — this module owns price-table, challenge
    envelope, on-chain verification. Nothing else.
  • Open/Closed — adding the GOAT rail to `agent_main.py` does not modify
    the Base or Somnia code paths.
  • Dependency Inversion — `GoatPaywallVerifier` takes its `Web3` instance
    via constructor so tests inject mocks.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any

from web3 import Web3

from app.config import get_settings

log = logging.getLogger(__name__)


# ─── Constants — match agent-provider/paywall.ts 1:1 ──────────────────────
_TX_REUSE_WINDOW_SECONDS = 60
_MAX_RECEIPT_RETRIES = 6
_RECEIPT_BACKOFF_SECONDS = 1.5
_TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
# keccak256("Transfer(address,address,uint256)")
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


# ─── Price table — parity with Base/Somnia rails (Decision 3=a) ───────────
_ROUTE_PRICES_USD: dict[str, tuple[str, str, dict]] = {
    "/api/v2/agent/decisions": (
        "$0.001",
        "AI crypto trading signals — APE/FADE verdicts with confidence + "
        "track record. 60.8% accuracy across 5,816+ on-chain resolved "
        "predictions. Settled in WGBTC (configurable token) on GOAT testnet3.",
        {"decisions": [{"token": "BTC", "action": "APE", "confidence": 85,
                        "entry": 104250.5, "target": 105814.3, "stop": 102686.7}],
         "total": 1},
    ),
    "/api/v2/agent/prices": (
        "$0.001",
        "Real-time aggregated cryptocurrency prices. Settled on GOAT testnet3.",
        {"prices": [{"symbol": "BTC", "price": 104250.5, "source": "coingecko"}]},
    ),
    "/api/v2/agent/track-record": (
        "$0.01",
        "Historical prediction accuracy across 5,816+ on-chain resolved "
        "predictions. Settled on GOAT testnet3.",
        {"overall": {"total": 5816, "wins": 3534, "win_rate": 60.8}},
    ),
    "/api/v2/agent/context": (
        "$0.01",
        "Macro market context — ETF flows, sector rotation, oracle mood. "
        "Settled on GOAT testnet3.",
        {"oracle_mood": "bullish"},
    ),
}


# ─── Pure utilities (Task 2) ──────────────────────────────────────────────

def usd_to_token_wei(price_usd: str, token_usd_price: float, decimals: int) -> int:
    """Convert a `$x.xxx` USD string to the smallest unit of the configured token.

    Uses Decimal for precision so $0.001 @ $65k WGBTC@18-dec computes to
    15_384_615_384_615 wei without float drift. Floors to ≥1 wei to prevent
    dust → zero (which would let a buyer 'pay' 0 and pass verification).
    """
    if not price_usd or token_usd_price <= 0 or decimals < 0:
        raise ValueError("invalid price/decimals")
    cleaned = price_usd.strip().lstrip("$")
    usd = Decimal(cleaned)
    rate = Decimal(str(token_usd_price))
    factor = Decimal(10) ** decimals
    wei = (usd / rate * factor).quantize(Decimal(1), rounding=ROUND_DOWN)
    return max(1, int(wei))


def build_challenge_envelope(
    *, network: str, asset: str, pay_to: str, max_amount_wei: int, token_symbol: str
) -> str:
    """Build the base64-JSON `payment-required` envelope.

    Byte-compatible with `agent-provider/src/paywall.ts::buildChallenge` so the
    same buyer code (`x402-pay.mjs`) interoperates without modification.
    """
    envelope = {
        "x402Version": 2,
        "accepts": [{
            "scheme": "exact",
            "network": network,
            "maxAmountRequired": str(max_amount_wei),
            "asset": asset,
            "payTo": pay_to,
            "tokenSymbol": token_symbol,
        }],
    }
    return base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode()).decode()


# ─── Verifier (Task 3) ────────────────────────────────────────────────────

@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str | None = None
    payer: str | None = None
    value_wei: int | None = None


@dataclass(frozen=True)
class GoatRouteConfig:
    price_usd: str
    price_wei: int
    description: str
    output_example: dict


class GoatPaywallVerifier:
    """Validates a buyer-supplied tx hash claims a paid request.

    Flow (port of paywall.ts):
        1. Regex tx_hash format.
        2. Cache lookup — same (tx, route, value≥min) → instant ok; same tx
           but different route → blocked (one tx authorizes one call).
        3. Fetch receipt with bounded retry (covers the 2-5s submit→inclusion
           gap on GOAT testnet so polite retries don't 402 unfairly).
        4. status != 1 → tx_reverted.
        5. Walk logs; find a Transfer on the configured token contract whose
           `to == pay_to` and `value >= min_value_wei`. Capture payer.
        6. Cache the success for 60s.
    """

    def __init__(self, w3: Web3, token_address: str, pay_to: str):
        self._w3 = w3
        self._token = Web3.to_checksum_address(token_address)
        self._pay_to = Web3.to_checksum_address(pay_to)
        # tx_hash → (route, payer, value_wei, expires_at_unix)
        self._spent: dict[str, tuple[str, str, int, float]] = {}

    async def verify(self, tx_hash: str, route_key: str, min_value_wei: int) -> VerifyResult:
        if not _TX_HASH_RE.match(tx_hash or ""):
            return VerifyResult(ok=False, reason="invalid_tx_hash")

        # Cache check
        cached = self._spent.get(tx_hash)
        if cached:
            route, payer, value, exp = cached
            if exp < time.time():
                self._spent.pop(tx_hash, None)
            elif route == route_key and value >= min_value_wei:
                return VerifyResult(ok=True, payer=payer, value_wei=value)
            else:
                return VerifyResult(ok=False, reason="tx_already_spent_on_other_route")

        receipt = await self._fetch_receipt(tx_hash)
        if receipt is None:
            return VerifyResult(ok=False, reason="receipt_unavailable")
        if int(receipt.get("status", 0)) != 1:
            return VerifyResult(ok=False, reason="tx_reverted")

        match = self._find_matching_transfer(receipt, min_value_wei)
        if match is None:
            return VerifyResult(ok=False, reason="no_matching_transfer_to_pay_to")
        payer, value = match
        self._spent[tx_hash] = (route_key, payer, value, time.time() + _TX_REUSE_WINDOW_SECONDS)
        return VerifyResult(ok=True, payer=payer, value_wei=value)

    async def _fetch_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        # web3.py is sync — wrap per Kinetic's "async handlers must not call sync libs" rule.
        for _ in range(_MAX_RECEIPT_RETRIES):
            try:
                receipt = await asyncio.to_thread(
                    self._w3.eth.get_transaction_receipt, tx_hash
                )
                if receipt:
                    return dict(receipt)
            except Exception as e:
                log.debug("get_transaction_receipt retry: %s", e)
            await asyncio.sleep(_RECEIPT_BACKOFF_SECONDS)
        return None

    def _find_matching_transfer(
        self, receipt: dict[str, Any], min_value_wei: int
    ) -> tuple[str, int] | None:
        """Return (payer, value_wei) of the first qualifying Transfer log, or None."""
        for log_entry in receipt.get("logs", []):
            try:
                addr = log_entry.get("address")
                topics = log_entry.get("topics") or []
                if not addr or len(topics) < 3:
                    continue
                if Web3.to_checksum_address(addr) != self._token:
                    continue
                topic0 = topics[0].hex() if hasattr(topics[0], "hex") else str(topics[0])
                if topic0.lower() != _TRANSFER_TOPIC:
                    continue
                # Indexed `from` (topic 1), `to` (topic 2); value is in `data`.
                from_addr = "0x" + (topics[1].hex() if hasattr(topics[1], "hex") else str(topics[1]))[-40:]
                to_addr = "0x" + (topics[2].hex() if hasattr(topics[2], "hex") else str(topics[2]))[-40:]
                if Web3.to_checksum_address(to_addr) != self._pay_to:
                    continue
                data = log_entry.get("data")
                if hasattr(data, "hex"):
                    data = data.hex()
                value = int(str(data), 16) if data else 0
                if value < min_value_wei:
                    continue
                return Web3.to_checksum_address(from_addr), value
            except Exception as e:
                log.debug("transfer log decode skipped: %s", e)
                continue
        return None


# ─── Factory (Task 4) ─────────────────────────────────────────────────────

def get_goat_x402_middleware_args(
    prefix: str = "/goat-api",
) -> tuple[dict[str, GoatRouteConfig], GoatPaywallVerifier] | tuple[None, None]:
    """Build (routes, verifier) for the GOAT rail.

    Returns (None, None) when disabled or misconfigured — caller treats as
    'rail off, other rails untouched'. Mirrors the fail-soft posture of
    `get_somnia_x402_middleware_args`.
    """
    s = get_settings()
    if not s.goat_x402_enabled:
        return (None, None)
    if not s.goat_x402_receiver_address:
        log.warning("GOAT rail enabled but GOAT_X402_RECEIVER_ADDRESS is empty — disabling")
        return (None, None)

    try:
        w3 = Web3(Web3.HTTPProvider(s.goat_x402_rpc_url, request_kwargs={"timeout": 5}))
        verifier = GoatPaywallVerifier(
            w3=w3,
            token_address=s.goat_x402_token_address,
            pay_to=s.goat_x402_receiver_address,
        )
    except Exception as e:  # noqa: BLE001 — fail-soft so other rails stay up
        log.warning("GOAT verifier init failed (rail disabled): %s", e)
        return (None, None)

    routes: dict[str, GoatRouteConfig] = {}
    for path, (price_usd, desc, ex) in _ROUTE_PRICES_USD.items():
        price_wei = usd_to_token_wei(
            price_usd, s.goat_x402_token_usd_price, s.goat_x402_token_decimals
        )
        routes[f"GET {prefix}{path}"] = GoatRouteConfig(
            price_usd=price_usd, price_wei=price_wei,
            description=desc, output_example=ex,
        )
    log.info(
        "GOAT rail ready: %d routes on %s -> %s (token=%s @ $%s)",
        len(routes), s.goat_x402_network, s.goat_x402_rpc_url,
        s.goat_x402_token_symbol, s.goat_x402_token_usd_price,
    )
    return (routes, verifier)
