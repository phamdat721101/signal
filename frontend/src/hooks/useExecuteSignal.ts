import { useMutation } from '@tanstack/react-query';
import { config } from '../config';

/**
 * useExecuteSignal — POST /api/cards/{id}/execute
 *
 * Single Responsibility: HTTP adapter for the trading-signal execute
 * endpoint. The 5-layer risk guards (kill-switch, type, symbol,
 * idempotency, daily cap) live server-side in
 * `backend/app/trading_signal_engine.safe_execute`; this hook just
 * surfaces the result + structured error to the UI.
 */
export interface ExecuteResult {
  order_id: string;
  status: string;
  qty: string;
  avg_price: string;
  trade_id: number;
  symbol: string;
  side: 'long' | 'short';
}

export interface ExecuteErrorBody {
  code?: string;
  detail?: { code?: string } | string;
  [k: string]: unknown;
}

async function post(cardId: number, address: string): Promise<ExecuteResult> {
  const r = await fetch(`${config.backendUrl}/api/cards/${cardId}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address }),
  });
  if (!r.ok) {
    let body: ExecuteErrorBody = {};
    try { body = await r.json(); } catch { /* keep empty */ }
    const code = (typeof body.detail === 'object' && body.detail?.code) || body.code || `HTTP_${r.status}`;
    const err = new Error(String(code)) as Error & { status: number; body: ExecuteErrorBody };
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return r.json() as Promise<ExecuteResult>;
}

export function useExecuteSignal() {
  return useMutation({
    mutationFn: ({ cardId, address }: { cardId: number; address: string }) =>
      post(cardId, address),
  });
}
