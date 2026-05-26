import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

export interface TickerEntry {
  price_usd: number;
  volume_24h: number;
  change_24h: number;
  ts: number;
}

/**
 * Live price polling for visible cards.
 *
 * Polls `/api/ticker?addresses=...` every 5s while `enabled` is true and the
 * tab is foregrounded. Backend cache coalesces concurrent requests into one
 * upstream call per 5s globally, so DAU does not multiply API cost.
 *
 * Pass enabled=false (or empty addresses) to opt out, e.g. for cards that
 * are not the visible top of the stack.
 */
export function useTicker(addresses: string[], enabled: boolean = true) {
  const cleaned = addresses.filter(Boolean).map(a => a.toLowerCase());
  const key = [...cleaned].sort().join(',');
  return useQuery<Record<string, TickerEntry>>({
    queryKey: ['ticker', key],
    queryFn: async () => {
      const url = `${config.backendUrl}/api/ticker?addresses=${cleaned.join(',')}`;
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
