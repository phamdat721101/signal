"""Chain operations idempotency + retry layer.

Single responsibility: persist the state of every state-mutating chain call
(SignalRegistry, ConvictionEngine, RewardEngine, ProofOfAlpha, OracleAdapter,
CosmosDispatcher, VIPScoreAdapter, ...) so that:

1. Re-submitting with the same args is a no-op (idempotency via SHA256 key).
2. A process crash mid-tx is healed on next reconciler sweep (no double-resolve,
   no double-mint, no double-IBC).

Modeled on `x402_settler.py` — same state-machine shape, same reconciler cadence,
same fail-safe semantics. Read that module first if this is unfamiliar.

States:
    pending           — row inserted, tx not yet sent
    sent              — tx submitted, awaiting confirmation
    confirmed         — receipt seen, awaiting `n` confirmations
    final             — promoted by reconciler after enough confirmations
    failed_retryable  — transient error; reconciler retries up to MAX_RETRIES
    failed_terminal   — gave up after MAX_RETRIES (alerts via /api/health)

Idempotency key = SHA256(op_type | canonical_json(args)). Same args twice = same
row. Callers MUST NOT mutate args between calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Callable

from app.db import _get_conn
from app.error_tracker import error_tracker

log = logging.getLogger(__name__)

# Stuck-row thresholds (seconds). Match `x402_settler` defaults so on-call
# operators reason about both layers the same way.
_STUCK_GRACE_SECONDS = 5 * 60        # sweep `sent` rows older than this
_RETRY_GRACE_SECONDS = 60            # back off failed_retryable rows briefly
_MAX_RETRIES = 5
_FINAL_CONFIRMATIONS = 1             # evm-1 has fast finality; bump for mainnet


# ─────────────────────────────────────────────────────────── table init ──

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS chain_operations (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    op_type         TEXT NOT NULL,
    args_json       JSONB NOT NULL,
    status          TEXT NOT NULL,
    tx_hash         TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS chain_ops_status_updated_idx
    ON chain_operations (status, updated_at);
CREATE INDEX IF NOT EXISTS chain_ops_op_type_status_idx
    ON chain_operations (op_type, status);
"""


def init_table() -> None:
    """Create the chain_operations table if missing. Idempotent."""
    conn = _get_conn()
    if not conn:
        log.warning("chain_ops: DATABASE_URL not set — table init skipped")
        return
    try:
        with conn.cursor() as cur:
            cur.execute(_TABLE_DDL)
        log.info("chain_ops: table ready")
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────── core API ──

def compute_key(op_type: str, args: dict[str, Any]) -> str:
    """Stable idempotency key — SHA256 of op_type + canonical JSON of args.

    Canonical means sorted keys, no whitespace, default JSON encoder. Callers
    must keep `args` JSON-serializable; bytes should be hex-encoded.
    """
    payload = op_type + "|" + json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def submit(op_type: str, args: dict[str, Any], fn: Callable[[], str | None], *,
           key: str | None = None) -> str:
    """Idempotently execute a chain-mutating function.

    Args:
        op_type:  short identifier, e.g. 'oracle_exit_price', 'cosmos_nft_mirror'.
        args:     JSON-serializable dict; used to derive the idempotency key.
        fn:       0-arg callable that performs the chain write and returns tx_hash.
        key:      override idempotency key (rarely needed; tests only).

    Returns:
        tx_hash string. Empty string on terminal failure (caller decides whether
        to raise based on op_type).

    Behavior:
        - If a row with the same key exists in {confirmed, final} → returns its tx_hash.
        - If a row exists in {sent, pending}  → returns its tx_hash (do NOT re-send).
        - Otherwise inserts pending, calls fn(), records outcome, returns tx_hash.
    """
    key = key or compute_key(op_type, args)
    breaker = error_tracker.get_breaker(f"chain_ops:{op_type}", threshold=5, cooldown=300.0)

    conn = _get_conn()
    if not conn:
        # Fail-open in degraded mode — don't double-block business logic on DB outage.
        log.warning("chain_ops[%s] no DB; calling fn() without idempotency", op_type)
        return _run_fn(fn, breaker)

    try:
        # Atomic claim: insert pending row IFF no row exists yet.
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chain_operations (idempotency_key, op_type, args_json, status)
                VALUES (%s, %s, %s::jsonb, 'pending')
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                (key, op_type, json.dumps(args, default=str)),
            )
            inserted = cur.fetchone() is not None

        if not inserted:
            # Existing row — return its current tx_hash (or empty if still in flight).
            existing = _fetch_status(conn, key)
            if existing and existing["status"] in ("confirmed", "final"):
                log.debug("chain_ops[%s] hit (status=%s)", op_type, existing["status"])
                return existing["tx_hash"] or ""
            if existing and existing["status"] in ("sent", "pending"):
                log.info("chain_ops[%s] in flight (status=%s)", op_type, existing["status"])
                return existing["tx_hash"] or ""
            # Row exists but failed — let reconciler retry; don't double-execute now.
            log.info("chain_ops[%s] previously failed; reconciler will retry", op_type)
            return existing["tx_hash"] if existing else ""

        # Newly inserted — execute and record outcome.
        _set_status(conn, key, "sent", attempts_inc=1)
        try:
            tx_hash = _run_fn(fn, breaker) or ""
            _set_status(conn, key, "confirmed", tx_hash=tx_hash)
            log.info("chain_ops[%s] confirmed tx=%s", op_type, tx_hash[:16])
            return tx_hash
        except _RetryableError as e:
            _set_status(conn, key, "failed_retryable", error=str(e))
            log.warning("chain_ops[%s] retryable: %s", op_type, e)
            return ""
        except Exception as e:
            _set_status(conn, key, "failed_retryable", error=f"{type(e).__name__}: {e}")
            log.warning("chain_ops[%s] error: %s", op_type, e)
            return ""
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────── reconciler ──

def reconcile(get_receipt: Callable[[str], dict | None] | None = None,
              retry_fn: Callable[[str, dict], str | None] | None = None) -> dict:
    """One sweep of the reconciler. Safe to call from a scheduler job every 60s.

    Args:
        get_receipt: optional fn(tx_hash) -> {"status": 1|0, "blockNumber": int}
                     or None. Used to advance `sent` → `confirmed`/`failed_retryable`.
        retry_fn:    optional fn(op_type, args) -> tx_hash. Used to retry
                     `failed_retryable` rows. Pass None to skip retries this sweep.

    Returns:
        Counts dict: {"checked": n, "confirmed": n, "retried": n, "abandoned": n}
    """
    conn = _get_conn()
    if not conn:
        return {"checked": 0, "confirmed": 0, "retried": 0, "abandoned": 0}
    counts = {"checked": 0, "confirmed": 0, "retried": 0, "abandoned": 0}
    try:
        # 1) sent → confirmed/failed_retryable (if get_receipt provided)
        if get_receipt is not None:
            with conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT idempotency_key, tx_hash FROM chain_operations
                     WHERE status='sent'
                       AND tx_hash IS NOT NULL
                       AND updated_at < NOW() - %s * INTERVAL '1 second'
                     LIMIT 100
                    """,
                    (_STUCK_GRACE_SECONDS,),
                )
                rows = cur.fetchall()
            for r in rows:
                counts["checked"] += 1
                receipt = _safe_call(get_receipt, r["tx_hash"])
                if not receipt:
                    continue
                if receipt.get("status") == 1:
                    _set_status(conn, r["idempotency_key"], "confirmed")
                    counts["confirmed"] += 1
                elif receipt.get("status") == 0:
                    _set_status(conn, r["idempotency_key"], "failed_retryable",
                                error="receipt status=0 (reverted)")

        # 2) confirmed → final after enough block depth (simplified: time-based)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chain_operations
                   SET status='final', updated_at=NOW()
                 WHERE status='confirmed'
                   AND updated_at < NOW() - INTERVAL '30 seconds'
                """
            )

        # 3) failed_retryable → retry (if retry_fn provided)
        if retry_fn is not None:
            with conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT idempotency_key, op_type, args_json, attempts FROM chain_operations
                     WHERE status='failed_retryable'
                       AND attempts < %s
                       AND updated_at < NOW() - %s * INTERVAL '1 second'
                     LIMIT 50
                    """,
                    (_MAX_RETRIES, _RETRY_GRACE_SECONDS),
                )
                rows = cur.fetchall()
            for r in rows:
                _set_status(conn, r["idempotency_key"], "sent", attempts_inc=1)
                tx_hash = _safe_call(retry_fn, r["op_type"], dict(r["args_json"])) or ""
                if tx_hash:
                    _set_status(conn, r["idempotency_key"], "confirmed", tx_hash=tx_hash)
                    counts["confirmed"] += 1
                else:
                    _set_status(conn, r["idempotency_key"], "failed_retryable",
                                error="retry returned empty tx_hash")
                counts["retried"] += 1

        # 4) attempts >= MAX_RETRIES → failed_terminal
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chain_operations
                   SET status='failed_terminal', updated_at=NOW()
                 WHERE status='failed_retryable'
                   AND attempts >= %s
                """,
                (_MAX_RETRIES,),
            )
            counts["abandoned"] = cur.rowcount or 0

        return counts
    finally:
        conn.close()


def pending_count() -> int:
    """For /api/health. Returns count of rows in non-terminal states."""
    conn = _get_conn()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM chain_operations "
                "WHERE status IN ('pending','sent','failed_retryable')"
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────── internals ──

class _RetryableError(Exception):
    """Mark errors as transient so reconciler retries (vs failed_terminal)."""


def _run_fn(fn: Callable[[], str | None], breaker) -> str:
    if breaker.is_open:
        raise _RetryableError("circuit open")
    try:
        result = fn()
        breaker.record_success()
        return result or ""
    except Exception:
        breaker.record_failure()
        raise


def _set_status(conn, key: str, status: str, *, tx_hash: str | None = None,
                error: str | None = None, attempts_inc: int = 0) -> None:
    sets = ["status=%s", "updated_at=NOW()"]
    params: list[Any] = [status]
    if tx_hash is not None:
        sets.append("tx_hash=%s")
        params.append(tx_hash)
    if error is not None:
        sets.append("last_error=%s")
        params.append(error[:500])
    if attempts_inc:
        sets.append("attempts=attempts+%s")
        params.append(attempts_inc)
    params.append(key)
    sql = f"UPDATE chain_operations SET {', '.join(sets)} WHERE idempotency_key=%s"
    with conn.cursor() as cur:
        cur.execute(sql, params)


def _fetch_status(conn, key: str) -> dict | None:
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT status, tx_hash FROM chain_operations WHERE idempotency_key=%s",
            (key,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _safe_call(fn: Callable, *args) -> Any:
    try:
        return fn(*args)
    except Exception as e:
        log.warning("chain_ops reconciler callback failed: %s", e)
        return None
