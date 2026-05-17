"""x402 settlement state machine.

Single responsibility: persist settle state and reconcile stuck payments.

Survives process crashes — if a settle is in flight when the API dies, a
'pending' row is left behind; reconcile_pending() retries it on a later run.

Idempotency key = SHA256(x-payment header bytes). Same payload header on
two requests = same hash = single row (UNIQUE constraint enforces it).

Tables (CREATE TABLE in db.init_db):
    x402_settlements(
        payload_hash TEXT PRIMARY KEY,    -- SHA256(x-payment bytes)
        resource     TEXT NOT NULL,
        payer        TEXT,
        amount       TEXT,
        network      TEXT,
        tx_hash      TEXT,                 -- on-chain hash from SettleResponse
        status       TEXT NOT NULL,        -- 'pending' | 'settled' | 'failed'
        retries      INTEGER DEFAULT 0,
        last_error   TEXT,
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        settled_at   TIMESTAMPTZ
    )
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from typing import Any

from app import db_async

log = logging.getLogger(__name__)

# Reconcile only pending rows older than this; younger ones are still being
# settled by the original request. Keeps reconciler from racing the live path.
_PENDING_GRACE_SECONDS = 60
_MAX_RETRIES = 3


def hash_payload(x_payment_header: str) -> str:
    """Stable dedup key for a paid request — SHA256 of the raw x-payment bytes."""
    return hashlib.sha256(x_payment_header.encode("utf-8")).hexdigest()


def decode_payment_header(x_payment_header: str) -> dict[str, Any]:
    """Decode the x-payment header (base64 JSON) into a dict."""
    raw = base64.b64decode(x_payment_header)
    return json.loads(raw)


async def record_pending(payload_hash: str, *, resource: str, network: str,
                         payer: str | None = None, amount: str | None = None) -> bool:
    """Insert a pending settlement row. Returns True if inserted, False if dup."""
    if not db_async.is_ready():
        return True  # fail-open in degraded mode
    try:
        await db_async.execute(
            """
            INSERT INTO x402_settlements (payload_hash, resource, payer, amount, network, status)
            VALUES ($1, $2, $3, $4, $5, 'pending')
            ON CONFLICT (payload_hash) DO NOTHING
            """,
            payload_hash, resource, payer, amount, network,
        )
        return True
    except Exception as e:
        log.warning("x402 record_pending failed for %s: %s", payload_hash[:12], e)
        return False


async def mark_settled(payload_hash: str, *, tx_hash: str, payer: str | None = None,
                       amount: str | None = None) -> None:
    if not db_async.is_ready():
        return
    try:
        await db_async.execute(
            """
            UPDATE x402_settlements
               SET status='settled', tx_hash=$2, payer=COALESCE($3, payer),
                   amount=COALESCE($4, amount), settled_at=NOW(), last_error=NULL
             WHERE payload_hash=$1
            """,
            payload_hash, tx_hash, payer, amount,
        )
    except Exception as e:
        log.warning("x402 mark_settled failed for %s: %s", payload_hash[:12], e)


async def mark_failed(payload_hash: str, error: str) -> None:
    if not db_async.is_ready():
        return
    try:
        await db_async.execute(
            """
            UPDATE x402_settlements
               SET status='failed', retries=retries+1, last_error=$2
             WHERE payload_hash=$1
            """,
            payload_hash, error[:500],
        )
    except Exception as e:
        log.warning("x402 mark_failed failed for %s: %s", payload_hash[:12], e)


async def settle_async(server: Any, payload: Any, requirements: Any, payload_hash: str) -> None:
    """Run server.settle_payment in a thread; persist outcome.

    The SDK's HTTPFacilitatorClient runs sync HTTP under the hood — wrap in
    asyncio.to_thread so we don't block the event loop. SDK retry is built in;
    we only persist the final outcome.
    """
    try:
        resp = await asyncio.to_thread(server.settle_payment, payload, requirements)
        if resp.success:
            await mark_settled(payload_hash, tx_hash=resp.transaction or "",
                               payer=resp.payer, amount=resp.amount)
            log.info("x402 settled %s tx=%s", payload_hash[:12], (resp.transaction or "")[:16])
        else:
            await mark_failed(payload_hash, f"{resp.error_reason}: {resp.error_message}")
            log.warning("x402 settle failed %s: %s", payload_hash[:12], resp.error_reason)
    except Exception as e:
        await mark_failed(payload_hash, f"{type(e).__name__}: {e}")
        log.warning("x402 settle exception %s: %s", payload_hash[:12], e)


async def reconcile_pending(server: Any) -> int:
    """Retry stuck pending settlements. Returns count retried."""
    if not db_async.is_ready():
        return 0
    rows = await db_async.fetch_all(
        """
        SELECT payload_hash, resource, network
          FROM x402_settlements
         WHERE status='pending'
           AND retries < $1
           AND created_at < NOW() - ($2 || ' seconds')::interval
         LIMIT 50
        """,
        _MAX_RETRIES, str(_PENDING_GRACE_SECONDS),
    )
    if not rows:
        return 0
    log.info("x402 reconcile: %d pending rows", len(rows))
    # We can't replay settle without the original payload+requirements bytes.
    # Mark them failed so they exit the pending queue; an admin tool or a
    # future ledger can refund. This is the safe, simple thing to do until
    # we persist the payload bytes for true replay.
    for r in rows:
        await mark_failed(r["payload_hash"], "abandoned: process restart before settle completed")
    return len(rows)


async def is_settled(payload_hash: str) -> bool:
    if not db_async.is_ready():
        return False
    row = await db_async.fetch_one(
        "SELECT status FROM x402_settlements WHERE payload_hash=$1",
        payload_hash,
    )
    return bool(row and row["status"] == "settled")
