import { useCallback } from 'react';
import { useSummonTransaction } from './useSummonTransaction';
import type { Card } from './useCards';

/**
 * useApeTransaction — backwards-compat shim around useSummonTransaction.
 *
 * The old hook had a `chainId === 1952` branch that was unreachable because
 * wagmi only registered Initia. 1952 turned out to be the correct chain id
 * for X Layer's Terigon testnet at testrpc.xlayer.tech (NOT 195 from
 * chainlist.org — that's a different RPC). The new useSummonTransaction is
 * chain-aware: it routes by card.chain_id and handles approve+playCard on
 * X Layer or createSignal on Initia. This shim exposes the legacy
 * `{ apeOnChain, isLoading, error }` shape so Feed.tsx keeps working
 * without an edit.
 *
 * Migrate Feed.tsx to import useSummonTransaction directly when next-touched.
 */
export function useApeTransaction() {
  const { summon, isLoading, error } = useSummonTransaction();

  const apeOnChain = useCallback(async (card: Card): Promise<string | null> => {
    const r = await summon(card);
    return r ? r.txHash : null;
  }, [summon]);

  return { apeOnChain, isLoading, error };
}
