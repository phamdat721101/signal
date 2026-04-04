import { useState } from 'react';
import { encodeFunctionData } from 'viem';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { config, customChain } from '../config';
import { SIGNAL_REGISTRY_ABI } from '../abi/SignalRegistry';
import { useQueryClient } from '@tanstack/react-query';

type TxStatus = 'idle' | 'pending' | 'success' | 'error';

export function useSignalActions() {
  const [status, setStatus] = useState<TxStatus>('idle');
  const [txHash, setTxHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { initiaAddress, requestTxBlock } = useInterwovenKit();

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
      if (!initiaAddress) throw new Error('No wallet connected');

      const data = encodeFunctionData({
        abi: SIGNAL_REGISTRY_ABI,
        functionName: 'createSignal',
        args: [asset as `0x${string}`, isBull, confidence, targetPrice, entryPrice],
      });

      console.log('[Signal] Executing tx...');
      const result = await requestTxBlock({
        chainId: customChain.chain_id,
        messages: [{
          typeUrl: '/minievm.evm.v1.MsgCall',
          value: {
            sender: initiaAddress.toLowerCase(),
            contractAddr: config.contractAddress,
            input: data,
            value: '0',
            accessList: [],
            authList: [],
          },
        }],
      });

      console.log('[Signal] TX result:', result);
      setTxHash(result?.transactionHash || null);
      setStatus('success');
      queryClient.invalidateQueries({ queryKey: ['signals'] });
      queryClient.invalidateQueries({ queryKey: ['signalCount'] });
      queryClient.invalidateQueries({ queryKey: ['userSignals'] });
    } catch (e: any) {
      console.error('[Signal] TX error:', e);
      setError(e.message || 'Transaction failed');
      setStatus('error');
    }
  };

  const reset = () => {
    setStatus('idle');
    setTxHash(null);
    setError(null);
  };

  return { executeSignal, status, txHash, error, reset, connected: !!initiaAddress };
}
