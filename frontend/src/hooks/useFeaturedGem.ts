import { useQuery } from '@tanstack/react-query';
import type { Card } from './useCards';
import { config } from '../config';

/**
 * The single highest-scoring gem from the last 24 hours.
 *
 * Used by Feed to ensure the first card after splash is always the freshest
 * gem (D1=C of the Hidden Gem at First Open PRD), regardless of what the
 * generic /api/cards feed happens to return at the top.
 *
 * Cached for 60s to match the backend's max-age=60. SW SWR handles offline.
 */
export function useFeaturedGem() {
  return useQuery<Card | null>({
    queryKey: ['featured-gem'],
    queryFn: async () => {
      const r = await fetch(`${config.backendUrl}/api/featured-gem`);
      if (!r.ok) return null;
      return r.json();
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}
