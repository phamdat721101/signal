"""IBC settlement event listener.

Subscribes to the IBCSettlementHook.ReportPaid event on evm-1 and credits
the corresponding report in the DB. Idempotent via chain_operations
(idempotency_key = sha256(eventTxHash | logIndex | reportId)) so a listener
restart never double-credits.

Single responsibility: poll/subscribe → write `chain_operations` row →
mark report paid. Heavy lifting (PDF generation, notifications) lives in
report_generator.py and triggers off the report_paid status.

Run as a long-lived asyncio task in scheduler_worker (Task 14 wires it).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app import chain_ops, db_async
from app.chain import ChainClient
from app.config import get_settings

log = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 10
_LOOKBACK_BLOCKS = 200       # on cold-start, scan this far back to catch missed events
_REPORT_PAID_TOPIC = None    # set lazily — keccak256("ReportPaid(address,string,uint256,uint256)")


async def run() -> None:
    """Long-lived listener loop. Returns only on cancellation."""
    settings = get_settings()
    hook_addr = getattr(settings, "ibc_settlement_hook_address", "") or ""
    if not hook_addr:
        log.info("ibc_listener: ibc_settlement_hook_address not configured; sleeping")
        # idle loop so the task is alive but does nothing
        while True:
            await asyncio.sleep(60)
    chain = ChainClient()
    last_block = chain.w3.eth.block_number - _LOOKBACK_BLOCKS
    log.info("ibc_listener: starting at block %d hook=%s", last_block, hook_addr)
    while True:
        try:
            head = chain.w3.eth.block_number
            if head > last_block:
                events = await asyncio.to_thread(_fetch_events, chain, hook_addr, last_block + 1, head)
                for ev in events:
                    await _process_event(ev)
                last_block = head
        except Exception as e:
            log.warning("ibc_listener: poll error: %s", e)
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _fetch_events(chain: ChainClient, hook_addr: str, from_block: int, to_block: int) -> list[dict]:
    """Synchronous web3.py event fetch — wrap in asyncio.to_thread from the loop."""
    from web3 import Web3
    abi = [{
        "type": "event",
        "name": "ReportPaid",
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "buyer",     "type": "address"},
            {"indexed": False, "name": "reportId",  "type": "string"},
            {"indexed": False, "name": "amount",    "type": "uint256"},
            {"indexed": False, "name": "sessionId", "type": "uint256"},
        ],
    }]
    contract = chain.w3.eth.contract(address=Web3.to_checksum_address(hook_addr), abi=abi)
    logs = contract.events.ReportPaid().get_logs(from_block=from_block, to_block=to_block)
    out = []
    for lg in logs:
        out.append({
            "tx_hash": lg["transactionHash"].hex(),
            "log_index": int(lg["logIndex"]),
            "buyer": lg["args"]["buyer"],
            "report_id": lg["args"]["reportId"],
            "amount": int(lg["args"]["amount"]),
            "session_id": int(lg["args"]["sessionId"]),
            "block": int(lg["blockNumber"]),
        })
    return out


async def _process_event(ev: dict[str, Any]) -> None:
    """Idempotently credit the report. Safe under listener restarts."""
    key = chain_ops.compute_key("ibc_report_credit", {
        "tx_hash": ev["tx_hash"],
        "log_index": ev["log_index"],
        "report_id": ev["report_id"],
    })
    # Use chain_ops.submit purely for the idempotency record — the "fn" here is
    # a no-op chain call (we already saw the on-chain effect). Returning the
    # event tx_hash keeps the row pointing at on-chain truth.
    chain_ops.submit("ibc_report_credit",
                     args={"tx_hash": ev["tx_hash"], "log_index": ev["log_index"],
                           "report_id": ev["report_id"]},
                     fn=lambda: ev["tx_hash"],
                     key=key)
    if not db_async.is_ready():
        return
    try:
        await db_async.execute(
            """
            UPDATE reports
               SET status = 'paid',
                   buyer = $1,
                   ibc_tx_hash = $2,
                   paid_at = NOW()
             WHERE id = $3
               AND status != 'paid'
            """,
            ev["buyer"], ev["tx_hash"], ev["report_id"],
        )
    except Exception as e:
        # `reports` table may not have the new columns yet — non-fatal. The
        # chain_operations row remains as the durable record.
        log.warning("ibc_listener: report mark-paid failed for %s: %s", ev["report_id"], e)
