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
  token_address?: string;
  institutional_context?: Array<{emoji: string; label: string; value: string; sentiment: string}>;
  verdict?: string;
  verdict_reason?: string;
  risk_level?: string;
  risk_score?: number;
  notification_hook?: string;
  sparkline?: number[];
  patterns?: { type: string; direction: string; label: string; description: string; lesson?: string }[];
  ohlc?: number[][];
  confidence?: number;
  debate_summary?: string;
  agent_reports?: { technical?: string; sentiment?: string; fundamentals?: string };
  trade_plan?: { entry?: string; target?: string; stop?: string; position_size?: string };
  trading_lesson?: string;
  position_guide?: string;
  why_now?: string;
  expected_outcome?: string;
  pattern_stats?: { pattern: string; win_rate: number; samples: number };
  risk_breakdown?: { factor: string; impact: string; direction: string }[];
  confluence?: { timeframes: { period: string; direction: string; strength: number }[]; confluence_score: number };
  rarity?: 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary';
  tvl?: number;
  tvl_change_1d?: number;
  source?: string;
  sentiment_score?: number;
  sentiment_direction?: 'bullish' | 'bearish' | 'neutral';
  research_summary?: { source: string; summary: string; sentiment: string; key_findings: string[]; chart_url: string };
  // ── Liquidity-Pool enrichment (populated for card_type === 'pool') ──
  token0_address?: string;
  token1_address?: string;
  token0_symbol?: string;
  token1_symbol?: string;
  token0_decimals?: number;
  token1_decimals?: number;
  pool_address?: string;
  chain_id?: number;
  dex_link?: string;
  volatility_7d_sigma?: number | null;
}

async function fetchCards(offset = 0, limit = 20, cardType?: string | string[]) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (cardType) {
    const value = Array.isArray(cardType) ? cardType.join(',') : cardType;
    if (value) params.set('card_type', value);
  }
  const resp = await fetch(`${config.backendUrl}/api/cards?${params.toString()}`);
  if (!resp.ok) throw new Error('Failed to fetch cards');
  return resp.json() as Promise<{ cards: Card[]; total: number }>;
}

export function useCards(offset = 0, limit = 20, cardType?: string | string[]) {
  const key = Array.isArray(cardType) ? cardType.join(',') : cardType;
  return useQuery({ queryKey: ['cards', offset, limit, key], queryFn: () => fetchCards(offset, limit, cardType) });
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
