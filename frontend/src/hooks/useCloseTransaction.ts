import { useCallback, useState } from 'react';
import { useSwitchChain } from 'wagmi';
import { config, isXLayer } from '../config';
import { useWallet } from './useWallet';

/**
 * useCloseTransaction — close (remove LP) for a played card on X Layer.
 * Mirrors useSummonTransaction but calls /api/cards/{id}/close.
 * No approvals needed for remove liquidity — single call.
 */
export function useCloseTransaction() {
  const { sendTx, isConnected, chainId, address } = useWallet();
  const { switchChainAsync } = useSwitchChain();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = useCallback(async (cardId: number, targetChain = 1952): Promise<string | null> => {
    if (!isConnected || !address) { setError('Connect wallet first'); return null; }
    setError(null); setIsLoading(true);

    try {
      if (chainId !== targetChain) await switchChainAsync({ chainId: targetChain });

      const resp = await fetch(`${config.backendUrl}/api/cards/${cardId}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address }),
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        throw new Error(j?.detail || `Backend: ${resp.status}`);
      }
      const bundle = await resp.json() as { calls: Array<{ to: string; data: string }> };

      const txHash = await sendTx(bundle.calls[0].to, bundle.calls[0].data, targetChain);
      setIsLoading(false);
      return txHash;
    } catch (e: any) {
      setError(e?.message || 'Close failed');
      setIsLoading(false);
      return null;
    }
  }, [chainId, isConnected, address, sendTx, switchChainAsync]);

  return { close, isLoading, error };
}
