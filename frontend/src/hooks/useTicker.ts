import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

export interface TickerEntry {
  price_usd: number;
  volume_24h?: number;
  change_24h?: number;
  progress?: number;       // Flap-only — % to DEX graduation, 0-1
  status?: string;         // Flap-only — Tradable / DEX / Staged / etc
  tax_rate_bps?: number;   // Flap-only — basis points
  ts: number;
}

/**
 * Live price polling for visible cards.
 *
 * source='dex' (default) hits /api/ticker (DEXScreener bulk). source='flap'
 * hits /api/ticker-flap, which reads Portal.getTokenV7 directly — needed
 * pre-graduation when the token has no DEX pool yet.
 *
 * Backend cache coalesces concurrent requests into one upstream call per 5s
 * globally, so DAU does not multiply API cost.
 */
export function useTicker(addresses: string[], enabled: boolean = true, source: 'dex' | 'flap' = 'dex') {
  const cleaned = addresses.filter(Boolean).map(a => a.toLowerCase());
  const key = [...cleaned].sort().join(',');
  const path = source === 'flap' ? '/api/ticker-flap' : '/api/ticker';
  return useQuery<Record<string, TickerEntry>>({
    queryKey: ['ticker', source, key],
    queryFn: async () => {
      const url = `${config.backendUrl}${path}?addresses=${cleaned.join(',')}`;
      const r = await fetch(url);
      if (!r.ok) return {};
      return r.json();
    },
    enabled: enabled && cleaned.length > 0,
    refetchInterval: enabled ? 5000 : false,
    refetchIntervalInBackground: false,
    staleTime: 4000,
    retry: 1,
  });
}
