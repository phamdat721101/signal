import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { config } from '../config';

export type Metric = string | { emoji: string; label: string; value: string; sentiment: string };

export interface Card {
  id: number;
  token_symbol: string;
  token_name: string;
  chain: string;
  hook: string;
  roast: string;
  metrics: Metric[];
  image_url: string;
  price: number;
  price_change_24h: number;
  volume_24h: number;
  market_cap: number;
  status: string;
  created_at: string;
  card_type?: string;
  institutional_context?: Array<{emoji: string; label: string; value: string; sentiment: string}>;
  verdict?: string;
  verdict_reason?: string;
  risk_level?: string;
  risk_score?: number;
  notification_hook?: string;
  sparkline?: number[];
  patterns?: { type: string; direction: string; label: string; description: string; lesson?: string }[];
  trading_lesson?: string;
  position_guide?: string;
  why_now?: string;
  expected_outcome?: string;
  pattern_stats?: { pattern: string; win_rate: number; samples: number };
  risk_breakdown?: { factor: string; impact: string; direction: string }[];
  confluence?: { timeframes: { period: string; direction: string; strength: number }[]; confluence_score: number };
  tvl?: number;
  tvl_change_1d?: number;
  source?: string;
}

async function fetchCards(offset = 0, limit = 20) {
  const resp = await fetch(`${config.backendUrl}/api/cards?offset=${offset}&limit=${limit}`);
  if (!resp.ok) throw new Error('Failed to fetch cards');
  return resp.json() as Promise<{ cards: Card[]; total: number }>;
}

export function useCards(offset = 0, limit = 20) {
  return useQuery({ queryKey: ['cards', offset, limit], queryFn: () => fetchCards(offset, limit) });
}

function swipeMutation(action: 'ape' | 'fade') {
  return async ({ cardId, address }: { cardId: number; address: string }) => {
    const resp = await fetch(`${config.backendUrl}/api/cards/${cardId}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address }),
    });
    if (!resp.ok) throw new Error(`${action} failed`);
    return resp.json();
  };
}

export function useSwipe(action: 'ape' | 'fade') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: swipeMutation(action),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cards'] }),
  });
}
