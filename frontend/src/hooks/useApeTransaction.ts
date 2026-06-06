import { useCallback } from 'react';
import { useSummonTransaction } from './useSummonTransaction';
import type { Card } from './useCards';

/**
 * useApeTransaction — backwards-compat shim around useSummonTransaction.
 *
 * Exposes the legacy `{ apeOnChain, isLoading, error }` shape so Feed.tsx
 * keeps working. Migrate to `useSummonTransaction` directly when touched.
 */
export function useApeTransaction() {
  const { summon, isLoading, error } = useSummonTransaction();

  const apeOnChain = useCallback(async (card: Card): Promise<string | null> => {
    const r = await summon(card);
    return r ? r.txHash : null;
  }, [summon]);

  return { apeOnChain, isLoading, error };
}
