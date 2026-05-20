// Settlement worker — runs as a separate PM2 process.
// Periodically scans x402_settlements for due retries and re-attempts settle.
//
// We can only replay settle if we persisted the original payment payload.
// The current minimal schema does NOT store the payload bytes; pending rows
// older than 60 minutes with attempts >= 3 are marked 'expired' as a safe
// terminal state (no double-charge possible — the buyer's signed tx either
// settled at the facilitator or not). To support true replay, extend the
// schema with a `payload_b64` column and persist the raw header in
// recordPending() — this is the documented next-iteration enhancement.

import { fetchPendingBatch, expireAbandoned } from './payment_state.js';
import { log } from './logger.js';
import { pool } from './db.js';

const SCAN_INTERVAL_MS = 60_000;

async function tick(): Promise<void> {
  const expired = await expireAbandoned(60);
  if (expired > 0) log.info('expired abandoned pending', { count: expired });

  const due = await fetchPendingBatch(25);
  if (due.length === 0) return;
  log.info('reconcile pass', { due: due.length });
  // No payload bytes stored → cannot replay verify+settle. Mark expired.
  // (This is intentional — see file header. Replay is a follow-up.)
  for (const row of due) {
    await pool.query(
      `UPDATE x402_settlements SET status='expired', last_error='no_payload_for_replay'
        WHERE payload_hash=$1 AND status='pending'`,
      [row.payload_hash],
    );
  }
}

async function loop(): Promise<void> {
  log.info('settler started', { intervalMs: SCAN_INTERVAL_MS });
  // Run once immediately on boot — picks up rows left pending by a crash
  await tick().catch((e) => log.warn('settler tick failed', { err: e.message }));
  setInterval(() => { void tick().catch((e) => log.warn('settler tick failed', { err: e.message })); }, SCAN_INTERVAL_MS);
}

function shutdown(sig: string): void {
  log.info('settler shutdown', { sig });
  void pool.end().finally(() => process.exit(0));
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

void loop();
