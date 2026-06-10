/**
 * v3 cross-chain LiFi hooks.
 *
 * SOLID:
 *  - SRP: this module exports two cohesive hooks + one shared client helper.
 *    `useLifiQuote` is a React-Query mutation. `useLifiIntentStatus` is a
 *    polling React-Query (2s interval) that auto-stops on terminal status.
 *  - OCP: the API base + endpoint paths are env-driven; auth header and
 *    x402 retry can be layered without changing the call sites.
 *  - DIP: hooks depend on the shared `request()` helper only.
 *
 * Status flow: PENDING → DELIVERED → EXECUTED  (success path)
 *           or PENDING → FAILED_REFUNDED       (timeout path)
 */
import { useMutation, useQuery } from '@tanstack/react-query';

const API_URL = import.meta.env.VITE_BACKEND_URL || '';

export type IntentStatus = 'PENDING' | 'DELIVERED' | 'EXECUTED' | 'FAILED_REFUNDED';

export interface LifiQuoteParams {
  fromChain: number;
  fromToken: `0x${string}`;
  swipeStakeUsdc: number;
  prophecyMarketId: number;
  userAddress: `0x${string}`;
  symbol: string;
  context: string;
}

export interface LifiQuoteResponse {
  intent_id: string;
  from_chain: number;
  from_token: string;
  to_chain: number;
  to_token: string;
  route_summary: { provider: string; estimated_seconds: number; fees_usd: number; slippage_bps: number };
  transaction_request: { to: `0x${string}`; data: `0x${string}`; value: string; gas_limit: string };
  kinetic_destination_calldata: string;
}

export interface LifiIntentStatusResponse {
  intent_id: string;
  status: IntentStatus;
  verdict_id: number | null;
  verdict_str: 'APE' | 'FADE' | null;
  card_hash: string | null;
  lifi_origin_tx_hash: string | null;
  dest_tx_hash: string | null;
  arbiscan_url: string | null;
  somnscan_url: string | null;
  prophecy_market_url: string | null;
  outcome_resolved: boolean;
  outcome_correct: boolean | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, init);
  if (resp.status === 402) {
    // x402 challenge — for v3 testnet we surface the body so the caller can
    // wire n-payment auto-pay later. Stub-quote fallback covers most demos.
    throw new Error(`PAYMENT_REQUIRED: ${await resp.text()}`);
  }
  if (!resp.ok) {
    let detail: unknown;
    try { detail = await resp.json(); } catch { detail = await resp.text(); }
    throw new Error(`HTTP ${resp.status}: ${JSON.stringify(detail)}`);
  }
  return resp.json() as Promise<T>;
}

export function useLifiQuote() {
  return useMutation<LifiQuoteResponse, Error, LifiQuoteParams>({
    mutationFn: async (params) => {
      const qs = new URLSearchParams({
        fromChain: String(params.fromChain),
        fromToken: params.fromToken,
        swipeStakeUsdc: String(params.swipeStakeUsdc),
        prophecyMarketId: String(params.prophecyMarketId),
        userAddress: params.userAddress,
        symbol: params.symbol,
        context: params.context,
      });
      return request<LifiQuoteResponse>(`/somnia-api/lifi-quote?${qs.toString()}`);
    },
  });
}

export function useLifiIntentStatus(intentId: string | null) {
  return useQuery<LifiIntentStatusResponse>({
    queryKey: ['lifi-intent-status', intentId],
    enabled: !!intentId,
    refetchInterval: (query) => {
      const status = (query.state.data as LifiIntentStatusResponse | undefined)?.status;
      // Stop polling once terminal.
      if (status === 'EXECUTED' || status === 'FAILED_REFUNDED') return false;
      return 2_000;
    },
    queryFn: () => request<LifiIntentStatusResponse>(`/api/v3/lifi-intent/${intentId}`),
  });
}

export async function reportOriginTx(intentId: string, txHash: `0x${string}`): Promise<void> {
  await request(`/api/v3/lifi-intent/${intentId}/origin-tx?tx_hash=${txHash}`, { method: 'POST' });
}
