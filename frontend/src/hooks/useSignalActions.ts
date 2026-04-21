import { useState } from 'react';
import { usePrivy } from '@privy-io/react-auth';
import { config } from '../config';
import { useQueryClient } from '@tanstack/react-query';

type TxStatus = 'idle' | 'pending' | 'success' | 'error';

export function useSignalActions() {
  const [status, setStatus] = useState<TxStatus>('idle');
  const [txHash, setTxHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { user } = usePrivy();
  const walletAddress = user?.wallet?.address || '';

  const executeSignal = async (
    asset: string,
    isBull: boolean,
    confidence: number,
    targetPrice: bigint,
    entryPrice: bigint,
  ) => {
    setStatus('pending');
    setError(null);
    setTxHash(null);

    try {
      if (!walletAddress) throw new Error('No wallet connected');
      const params = new URLSearchParams({
        asset, isBull: String(isBull), confidence: String(confidence),
        targetPrice: String(targetPrice), entryPrice: String(entryPrice),
        creator: walletAddress,
      });
      const resp = await fetch(`${config.backendUrl}/api/signals/execute?${params}`, { method: 'POST' });
      if (!resp.ok) throw new Error(`Backend: ${resp.status}`);
      const result = await resp.json();
      setTxHash(result.txHash);
      setStatus('success');
      queryClient.invalidateQueries({ queryKey: ['signals'] });
    } catch (e: any) {
      setError(e.message || 'Transaction failed');
      setStatus('error');
    }
  };

  const reset = () => { setStatus('idle'); setTxHash(null); setError(null); };

  return { executeSignal, status, txHash, error, reset, connected: !!walletAddress };
}
