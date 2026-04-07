import { useState, useCallback } from 'react';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { encodeFunctionData, parseEther } from 'viem';
import { config, customChain } from '../config';
import { useQueryClient } from '@tanstack/react-query';

const MOCK_IUSD_ABI = [
  { name: 'approve', type: 'function', inputs: [{ name: 'spender', type: 'address' }, { name: 'amount', type: 'uint256' }], outputs: [{ type: 'bool' }], stateMutability: 'nonpayable' },
  { name: 'balanceOf', type: 'function', inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }], stateMutability: 'view' },
  { name: 'faucet', type: 'function', inputs: [], outputs: [], stateMutability: 'nonpayable' },
] as const;

const SESSION_VAULT_ABI = [
  { name: 'createSession', type: 'function', inputs: [{ name: 'amount', type: 'uint256' }, { name: 'durationSeconds', type: 'uint256' }], outputs: [{ name: 'sessionId', type: 'uint256' }], stateMutability: 'nonpayable' },
  { name: 'closeSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }], outputs: [], stateMutability: 'nonpayable' },
] as const;

export type TxStep = {
  label: string;
  status: 'pending' | 'success' | 'error' | 'idle';
  txHash?: string;
  error?: string;
};

export function useSession() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<TxStep[]>([]);
  const { initiaAddress, requestTxBlock } = useInterwovenKit();
  const queryClient = useQueryClient();

  const updateStep = (index: number, update: Partial<TxStep>) => {
    setSteps(prev => prev.map((s, i) => i === index ? { ...s, ...update } : s));
  };

  const sendTx = useCallback(async (contractAddr: string, data: string): Promise<string | undefined> => {
    if (!initiaAddress) throw new Error('Wallet not connected');
    const result = await requestTxBlock({
      chainId: customChain.chain_id,
      messages: [{ typeUrl: '/minievm.evm.v1.MsgCall', value: { sender: initiaAddress.toLowerCase(), contractAddr, input: data, value: '0', accessList: [], authList: [] } }],
    });
    return result?.transactionHash;
  }, [initiaAddress, requestTxBlock]);

  const claimFaucet = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSteps([{ label: 'Claim 1000 iUSD from faucet', status: 'pending' }]);
    try {
      const hash = await sendTx(config.mockIUSDAddress, encodeFunctionData({ abi: MOCK_IUSD_ABI, functionName: 'faucet', args: [] }));
      updateStep(0, { status: 'success', txHash: hash });
    } catch (e: any) {
      const msg = e.message || 'Faucet failed';
      setError(msg);
      updateStep(0, { status: 'error', error: msg });
    } finally {
      setLoading(false);
    }
  }, [sendTx]);

  const approveAndDeposit = useCallback(async (amountIUSD: string, durationHours: number) => {
    setLoading(true);
    setError(null);
    setSteps([
      { label: `Approve ${amountIUSD} iUSD`, status: 'pending' },
      { label: `Deposit ${amountIUSD} iUSD (${durationHours}h session)`, status: 'idle' },
    ]);
    try {
      const amountWei = parseEther(amountIUSD);
      const approveHash = await sendTx(config.mockIUSDAddress, encodeFunctionData({ abi: MOCK_IUSD_ABI, functionName: 'approve', args: [config.sessionVaultAddress, amountWei] }));
      updateStep(0, { status: 'success', txHash: approveHash });
      updateStep(1, { status: 'pending' });
      const depositHash = await sendTx(config.sessionVaultAddress, encodeFunctionData({ abi: SESSION_VAULT_ABI, functionName: 'createSession', args: [amountWei, BigInt(durationHours * 3600)] }));
      updateStep(1, { status: 'success', txHash: depositHash });
      queryClient.invalidateQueries({ queryKey: ['session'] });
    } catch (e: any) {
      const msg = e.message || 'Transaction failed';
      setError(msg);
      setSteps(prev => prev.map(s => s.status === 'pending' ? { ...s, status: 'error', error: msg } : s));
    } finally {
      setLoading(false);
    }
  }, [sendTx, queryClient]);

  const clearSteps = useCallback(() => { setSteps([]); setError(null); }, []);

  return { approveAndDeposit, claimFaucet, clearSteps, loading, error, steps, connected: !!initiaAddress };
}
