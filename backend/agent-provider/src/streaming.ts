// Streaming SKU — Server-Sent Events stream of live trade decisions.
//
// Model: prepaid budget → entry payment via payment_gate (e.g. $0.05 = 100
// emits @ $0.0005). Server polls Python every 5s, emits on change, decrements
// budget, closes when exhausted. Session is persisted in streaming_sessions
// for resume after crash; if process restarts, the open SSE breaks and the
// buyer must reconnect with a new payment (we don't refund unused budget —
// future enhancement: integrate n-payment StreamingPaymentManager on Tempo).

import type { Request, Response } from 'express';
import crypto from 'node:crypto';
import { Agent, request as undiciRequest } from 'undici';
import { env } from './env.js';
import { log } from './logger.js';
import { pool } from './db.js';

const POLL_INTERVAL_MS = 5_000;
const HEARTBEAT_INTERVAL_MS = 15_000;
const PER_EMIT_USDC = 500n;            // $0.0005

const pollAgent = new Agent({ keepAliveTimeout: 30_000, connections: 4 });

async function pollDecisions(): Promise<{ id: number; token: string; action: string; confidence: number }[]> {
  try {
    const r = await undiciRequest(`${env.PYTHON_INTERNAL_URL}/api/v2/agent/decisions?limit=10`, {
      dispatcher: pollAgent, headersTimeout: 3_000, bodyTimeout: 5_000,
    });
    const text = await r.body.text();
    const j = JSON.parse(text);
    return Array.isArray(j?.decisions) ? j.decisions : [];
  } catch {
    return [];
  }
}

async function openSession(payer: string, network: string, budgetMicroUsdc: bigint): Promise<string> {
  const id = crypto.randomBytes(16).toString('hex');
  await pool.query(
    `INSERT INTO streaming_sessions (id, payer, tool_name, network, budget_remaining, status)
     VALUES ($1,$2,'live-decisions-stream',$3,$4,'open')`,
    [id, payer, network, budgetMicroUsdc.toString()],
  );
  return id;
}

async function debitSession(sessionId: string, amount: bigint): Promise<bigint> {
  const r = await pool.query<{ budget_remaining: string }>(
    `UPDATE streaming_sessions
        SET budget_remaining = budget_remaining - $2,
            unsettled_amount = unsettled_amount + $2
      WHERE id=$1 AND status='open' AND budget_remaining >= $2
      RETURNING budget_remaining`,
    [sessionId, amount.toString()],
  );
  if (!r.rows[0]) return -1n;
  return BigInt(r.rows[0].budget_remaining);
}

async function closeSession(sessionId: string, reason: string): Promise<void> {
  await pool.query(`UPDATE streaming_sessions SET status='closed', last_settled_at=NOW() WHERE id=$1`, [sessionId]);
  log.info('stream closed', { sessionId: sessionId.slice(0, 12), reason });
}

export async function streamHandler(req: Request, res: Response): Promise<void> {
  // Buyer must have prepaid via payment_gate; we look at audit row for budget basis.
  // The header `x-stream-budget` (in microUSDC) tells us how much they paid for the stream.
  const budget = BigInt(req.header('x-stream-budget') ?? '50000'); // default $0.05
  const payer = req.header('x-payment-payer') ?? 'unknown';
  const network = req.header('x-payment-network') ?? 'eip155:8453';

  res.status(200).set({
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.flushHeaders();

  const sessionId = await openSession(payer, network, budget).catch(() => null);
  if (!sessionId) {
    res.write(`event: error\ndata: ${JSON.stringify({ error: 'session_open_failed' })}\n\n`);
    res.end();
    return;
  }
  res.write(`event: session\ndata: ${JSON.stringify({ id: sessionId, budget: budget.toString(), perEmit: PER_EMIT_USDC.toString() })}\n\n`);

  let lastSeenIds = new Set<number>();
  let closed = false;
  const cleanup = (reason: string) => {
    if (closed) return;
    closed = true;
    clearInterval(pollTimer);
    clearInterval(heartbeatTimer);
    void closeSession(sessionId, reason);
    res.end();
  };
  req.on('close', () => cleanup('client_disconnect'));

  const heartbeatTimer = setInterval(() => {
    if (!closed) res.write(': heartbeat\n\n');
  }, HEARTBEAT_INTERVAL_MS);

  const pollTimer = setInterval(async () => {
    if (closed) return;
    const decisions = await pollDecisions();
    for (const d of decisions) {
      if (lastSeenIds.has(d.id)) continue;
      lastSeenIds.add(d.id);
      const remaining = await debitSession(sessionId, PER_EMIT_USDC);
      if (remaining < 0n) {
        res.write(`event: budget_exhausted\ndata: {}\n\n`);
        return cleanup('budget_exhausted');
      }
      res.write(`event: decision\ndata: ${JSON.stringify({ ...d, budget_remaining: remaining.toString() })}\n\n`);
    }
  }, POLL_INTERVAL_MS);
}
