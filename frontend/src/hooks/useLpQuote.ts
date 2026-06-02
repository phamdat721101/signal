/**
 * useLpQuote — fetch the LP recipe for a card + amount + preset.
 *
 * Single Responsibility: thin React Query wrapper over GET
 * `/api/cards/{cardId}/lp-recipe`. Disabled when amount_a is 0 — the
 * Configurator can show preset previews via `useLpRange` instead, with
 * zero network traffic.
 *
 * The 350ms debounce is via React Query's `staleTime` + the queryKey itself
 * containing the rounded amount; for rapid typing, we rely on React's
 * controlled-input batching to avoid spammy fetches.
 */
import { useQuery } from '@tanstack/react-query';
import { config } from '../config';
import type { LpPreset } from './useLpRange';

export interface LpRecipe {
  preset: LpPreset;
  sigma_7d: number | null;
  min_price: number | null;
  max_price: number | null;
  ticks: [number, number] | null;
  amount_a: number;
  token_b_amount: number;
  pool_share_pct: number;
  est_fee_24h_usd: number;
  user_tvl_usd?: number;
  supported: boolean;
  dex_link: string;
  reason?: string;
}

async function fetchRecipe(cardId: number, amountA: number, preset: LpPreset): Promise<LpRecipe> {
  const params = new URLSearchParams({
    amount_a: String(amountA),
    preset,
  });
  const resp = await fetch(`${config.backendUrl}/api/cards/${cardId}/lp-recipe?${params.toString()}`);
  if (!resp.ok) throw new Error(`recipe fetch failed (${resp.status})`);
  return (await resp.json()) as LpRecipe;
}

export function useLpQuote(
  cardId: number | undefined,
  amountA: number,
  preset: LpPreset
) {
  return useQuery<LpRecipe>({
    queryKey: ['lp-recipe', cardId, Number(amountA.toFixed(6)), preset],
    enabled: !!cardId && amountA > 0,
    queryFn: () => fetchRecipe(cardId!, amountA, preset),
    staleTime: 5_000,
  });
}
