"""Cross-chain resolution relay — Somnia mainnet 5031 → testnet 50312.

When prophecy.social resolves a market on mainnet, this poller:
  1. Pulls the recent `MarketResolved` events via `prophecy_social_reader.fetch_recent_resolutions`.
  2. For each resolved market, finds the matching Kinetic card row.
  3. Calls `KineticProphecyBridge.triggerResolution(marketId, outcome, receiptUri)` on testnet.
  4. The bridge then propagates to `ConvictionEngine.resolveCard` for every swiper.

Idempotency is handled three ways:
  - Bridge contract reverts `AlreadyPropagated` on the second call → we ignore.
  - DB lookup short-circuits markets we never carded.
  - Mainnet block-window scan re-reads each tick; downstream dedupe wins.

This module never raises into the scheduler — every error is logged.

SOLID:
  - SRP: read mainnet resolutions, push to bridge. No card pipeline, no DB
    writes beyond the cursor read.
  - DIP: depends on `prophecy_social_reader` for reads + `web3.py` for the
    bridge write; the contract addresses come from `Settings`.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import db, prophecy_social_reader as reader
from app.config import get_settings

log = logging.getLogger(__name__)

# Default scan window (mainnet blocks). Somnia targets sub-second blocks so
# 5,000 blocks ≈ 1.5h of history; bridge idempotency handles dupes anyway.
DEFAULT_WINDOW_BLOCKS = 5_000
DEFAULT_BATCH_LIMIT = 20

# Bridge ABI — only the function we send. Keeping it tiny mirrors the
# bind helper in `prophecy_card_pipeline._BRIDGE_BIND_ABI`.
_BRIDGE_TRIGGER_ABI = [
    {
        "type": "function",
        "name": "triggerResolution",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "prophecyMarketId", "type": "uint256"},
            {"name": "outcome", "type": "bool"},
            {"name": "receiptUri", "type": "string"},
        ],
        "outputs": [],
    }
]


def relay_recent_resolutions(window_blocks: int = DEFAULT_WINDOW_BLOCKS) -> int:
    """Scan recent mainnet resolutions and propagate them to the testnet bridge.

    Returns the count of resolutions we propagated (excludes no-ops / dupes).
    Always best-effort; never raises.
    """
    s = get_settings()
    if not s.prophecy_card_gen_enabled:
        return 0
    if not s.prophecy_bridge_address or not s.somnia_testnet_rpc or not s.private_key:
        log.info("prophecy_relay: missing config; skipping tick")
        return 0

    # Resolve scan window.
    w3, contract = reader._get_contract()                   # mainnet handle; lazy
    if contract is None or w3 is None:
        log.info("prophecy_relay: mainnet reader unavailable; skipping tick")
        return 0
    try:
        latest = int(w3.eth.block_number)
    except Exception as e:                                   # noqa: BLE001
        log.warning("prophecy_relay: latest-block read failed (%s)", e)
        latest = 0
    since = max(0, latest - int(window_blocks)) if latest else 0

    resolved = reader.fetch_recent_resolutions(since_block=since, limit=DEFAULT_BATCH_LIMIT)
    if not resolved:
        return 0

    propagated = 0
    for market in resolved:
        if not market.is_resolved or market.outcome is None:
            continue
        card_id = _card_id_for_market(market.id)
        if card_id is None:
            log.debug("prophecy_relay: no card for market_id=%d (skipped)", market.id)
            continue
        tx = _trigger_resolution(market.id, bool(market.outcome), market.receipt_uri or "")
        if tx is not None:
            propagated += 1
            log.info(
                "prophecy_relay: market_id=%d outcome=%s tx=%s",
                market.id, market.outcome, tx,
            )
        # v3.1 — propagate the outcome into matching cross-chain lifi_intents.
        # Idempotent: subsequent ticks find no rows with outcome_resolved=FALSE.
        # Runs even if `tx is None` (AlreadyPropagated) because lifi_intents
        # may have been inserted *after* the bridge already settled.
        try:
            n = db.mark_lifi_intents_outcome_for_market(int(market.id), bool(market.outcome))
            if n:
                log.info("prophecy_relay: marked %d lifi_intent(s) for market_id=%d", n, market.id)
        except Exception as e:                                   # noqa: BLE001
            log.warning("prophecy_relay: lifi_intents outcome propagation failed: %s", e)
    return propagated


def scheduled_prophecy_relay() -> None:
    """Cron entrypoint. Single-shot; idempotency is at the bridge contract."""
    try:
        n = relay_recent_resolutions()
        if n:
            log.info("prophecy_relay: propagated %d resolution(s)", n)
    except Exception as e:                                   # noqa: BLE001
        log.warning("prophecy_relay tick failed: %s", e)


# ─── Internals ────────────────────────────────────────────────────────


def _card_id_for_market(market_id: int) -> Optional[int]:
    conn = db._get_read_conn() if hasattr(db, "_get_read_conn") else db._get_conn()
    if not conn:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM cards WHERE prophecy_market_id = %s LIMIT 1",
            (int(market_id),),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def _trigger_resolution(market_id: int, outcome: bool, receipt_uri: str) -> Optional[str]:
    """Send `triggerResolution` to the testnet bridge. Returns tx hash or None.

    `AlreadyPropagated` reverts are intentionally swallowed — the bridge
    has already settled this market in a previous tick, so this is the
    success-equivalent on retry.
    """
    s = get_settings()
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(s.somnia_testnet_rpc, request_kwargs={"timeout": 10}))
        account = w3.eth.account.from_key(s.private_key)
        bridge = w3.eth.contract(
            address=Web3.to_checksum_address(s.prophecy_bridge_address),
            abi=_BRIDGE_TRIGGER_ABI,
        )
        tx = bridge.functions.triggerResolution(
            int(market_id), bool(outcome), receipt_uri,
        ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": 50312,
            "gas": 400_000,
            "gasPrice": w3.eth.gas_price or 1_000_000_000,
        })
        signed = account.sign_transaction(tx)
        return w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    except Exception as e:                                   # noqa: BLE001
        msg = str(e)
        if "AlreadyPropagated" in msg or "already propagated" in msg.lower():
            log.debug("prophecy_relay: market_id=%d already propagated", market_id)
            return None
        log.warning("prophecy_relay: triggerResolution(%d) failed: %s", market_id, e)
        return None
