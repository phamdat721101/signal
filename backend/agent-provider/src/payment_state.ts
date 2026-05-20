// Payment state — audit ledger + settlement state machine.
// Mirrors the Python x402_settler.py pattern: outbox + retry + idempotency.

import { pool } from './db.js';
import { log } from './logger.js';

// ─── Audit ──────────────────────────────────────────────────────────────────
export interface AuditEntry {
  toolName: string;
  network: string;
  payer: string;
  amount: string;
  payloadHash: string;
  status: 'verified' | 'settled' | 'failed';
  referenceKey?: string | null;
  requestId?: string | null;
}

export async function recordAudit(e: AuditEntry): Promise<void> {
  try {
    await pool.query(
      `INSERT INTO payment_audit (tool_name, network, payer, amount, payload_hash, status, reference_key, request_id)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
      [e.toolName, e.network, e.payer, e.amount, e.payloadHash, e.status, e.referenceKey ?? null, e.requestId ?? null],
    );
  } catch (err: any) {
    log.warn('audit insert failed', { err: err.message });
  }
}

// ─── Settlement state ───────────────────────────────────────────────────────
export interface PendingArgs {
  payloadHash: string;
  resource: string;
  network: string;
  payer: string | null;
  amount: string;
}

export async function recordPending(a: PendingArgs): Promise<void> {
  try {
    await pool.query(
      `INSERT INTO x402_settlements (payload_hash, resource, network, payer, amount, status, next_attempt_at)
       VALUES ($1,$2,$3,$4,$5,'pending', NOW())
       ON CONFLICT (payload_hash) DO NOTHING`,
      [a.payloadHash, a.resource, a.network, a.payer, a.amount],
    );
  } catch (e: any) {
    log.warn('record_pending failed', { err: e.message });
  }
}

export async function markSettled(payloadHash: string, txHash: string): Promise<void> {
  try {
    await pool.query(
      `UPDATE x402_settlements
          SET status='settled', tx_hash=$2, settled_at=NOW(), last_error=NULL
        WHERE payload_hash=$1`,
      [payloadHash, txHash],
    );
    await pool.query(`UPDATE payment_audit SET status='settled' WHERE payload_hash=$1`, [payloadHash]);
  } catch (e: any) {
    log.warn('mark_settled failed', { err: e.message });
  }
}

export async function markFailed(payloadHash: string, error: string): Promise<void> {
  try {
    // Exponential backoff: next_attempt_at = NOW() + 2^attempts * 30s, capped at 5
    await pool.query(
      `UPDATE x402_settlements
          SET status = CASE WHEN attempts + 1 >= 5 THEN 'expired' ELSE 'pending' END,
              attempts = attempts + 1,
              next_attempt_at = NOW() + (LEAST(POWER(2, attempts + 1), 32) * INTERVAL '30 seconds'),
              last_error = $2
        WHERE payload_hash=$1`,
      [payloadHash, error.slice(0, 500)],
    );
  } catch (e: any) {
    log.warn('mark_failed failed', { err: e.message });
  }
}

export async function isAlreadySettled(payloadHash: string): Promise<boolean> {
  try {
    const r = await pool.query(`SELECT status FROM x402_settlements WHERE payload_hash=$1`, [payloadHash]);
    return r.rows[0]?.status === 'settled';
  } catch {
    return false;
  }
}

// ─── Reconciler — used by separate settler process ──────────────────────────
export interface PendingRow {
  payload_hash: string;
  resource: string;
  network: string;
  payer: string | null;
  amount: string;
  attempts: number;
}

export async function fetchPendingBatch(limit = 25): Promise<PendingRow[]> {
  try {
    const r = await pool.query<PendingRow>(
      `SELECT payload_hash, resource, network, payer, amount, attempts
         FROM x402_settlements
        WHERE status='pending' AND next_attempt_at <= NOW()
        ORDER BY next_attempt_at ASC
        LIMIT $1
        FOR UPDATE SKIP LOCKED`,
      [limit],
    );
    return r.rows;
  } catch (e: any) {
    log.warn('fetch_pending failed', { err: e.message });
    return [];
  }
}

export async function expireAbandoned(olderThanMinutes = 60): Promise<number> {
  try {
    const r = await pool.query(
      `UPDATE x402_settlements
          SET status='expired', last_error='abandoned: no replay payload available'
        WHERE status='pending'
          AND created_at < NOW() - ($1 || ' minutes')::interval
          AND attempts >= 3
        RETURNING payload_hash`,
      [String(olderThanMinutes)],
    );
    return r.rowCount ?? 0;
  } catch {
    return 0;
  }
}
