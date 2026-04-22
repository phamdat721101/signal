import { useState, useCallback } from 'react';
import { usePrivy, useWallets } from '@privy-io/react-auth';
import { createPublicClient, encodeFunctionData, http, parseEther, formatEther } from 'viem';
import { config } from '../config';
import { useQueryClient, useQuery } from '@tanstack/react-query';

const MOCK_IUSD_ABI = [
  { name: 'approve', type: 'function', inputs: [{ name: 'spender', type: 'address' }, { name: 'amount', type: 'uint256' }], outputs: [{ type: 'bool' }], stateMutability: 'nonpayable' },
  { name: 'balanceOf', type: 'function', inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }], stateMutability: 'view' },
] as const;

const SESSION_VAULT_ABI = [
  { name: 'createSession', type: 'function', inputs: [{ name: 'amount', type: 'uint256' }, { name: 'durationSeconds', type: 'uint256' }], outputs: [{ name: 'sessionId', type: 'uint256' }], stateMutability: 'nonpayable' },
  { name: 'closeSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }], outputs: [], stateMutability: 'nonpayable' },
  { name: 'getUserSessions', type: 'function', inputs: [{ name: 'user', type: 'address' }], outputs: [{ name: '', type: 'uint256[]' }], stateMutability: 'view' },
  { name: 'getSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }], outputs: [{ name: '', type: 'tuple', components: [{ name: 'depositor', type: 'address' }, { name: 'depositAmount', type: 'uint256' }, { name: 'remainingBalance', type: 'uint256' }, { name: 'totalRedeemed', type: 'uint256' }, { name: 'voucherCount', type: 'uint256' }, { name: 'createdAt', type: 'uint256' }, { name: 'expiresAt', type: 'uint256' }, { name: 'active', type: 'bool' }] }], stateMutability: 'view' },
] as const;

export type TxStep = {
  label: string;
  status: 'pending' | 'success' | 'error' | 'idle';
  txHash?: string;
  error?: string;
};

const publicClient = createPublicClient({ chain: config.chain, transport: http() });

export function useSession() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<TxStep[]>([]);
  const { user } = usePrivy();
  const { wallets } = useWallets();
  const address = user?.wallet?.address || '';
  const queryClient = useQueryClient();

  const updateStep = (index: number, update: Partial<TxStep>) => {
    setSteps(prev => prev.map((s, i) => i === index ? { ...s, ...update } : s));
  };

  // Read iUSD balance
  const { data: iusdBalance, refetch: refetchBalance } = useQuery({
    queryKey: ['iusd-balance', address],
    queryFn: async () => {
      if (!address || config.mockIUSDAddress === '0x0000000000000000000000000000000000000000') return '0';
      const bal = await publicClient.readContract({
        address: config.mockIUSDAddress, abi: MOCK_IUSD_ABI,
        functionName: 'balanceOf', args: [address as `0x${string}`],
      });
      return formatEther(bal as bigint);
    },
    enabled: !!address,
    staleTime: 10_000,
  });

  // Send tx via Privy wallet with chain switch
  const sendTx = useCallback(async (contractAddr: string, data: string): Promise<string> => {
    const wallet = wallets.find(w => w.walletClientType === 'privy') || wallets[0];
    if (!wallet) throw new Error('No wallet connected');
    // Switch to correct chain
    try { await wallet.switchChain(config.chain.id); } catch { /* already on chain */ }
    const provider = await wallet.getEthereumProvider();
    const hash = await provider.request({
      method: 'eth_sendTransaction',
      params: [{ from: wallet.address, to: contractAddr, data, gas: '0x7A120', gasPrice: '0x0' }],
    });
    return hash as string;
  }, [wallets]);

  // Faucet: use backend endpoint (deployer mints to user — most reliable)
  const claimFaucet = useCallback(async () => {
    if (!address) return;
    setLoading(true); setError(null);
    setSteps([{ label: 'Claim 1000 iUSD from faucet', status: 'pending' }]);
    try {
      const resp = await fetch(`${config.backendUrl}/api/payment/faucet?address=${address}`, { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Faucet failed');
      updateStep(0, { status: 'success', txHash: data.txHash });
      refetchBalance();
    } catch (e: any) {
      setError(e.message);
      updateStep(0, { status: 'error', error: e.message });
    } finally { setLoading(false); }
  }, [address, refetchBalance]);

  // Deposit: approve + createSession via user wallet
  const approveAndDeposit = useCallback(async (amountIUSD: string, durationHours: number) => {
    setLoading(true); setError(null);
    setSteps([
      { label: `Approve ${amountIUSD} iUSD`, status: 'pending' },
      { label: `Deposit ${amountIUSD} iUSD (${durationHours}h session)`, status: 'idle' },
    ]);
    try {
      const amountWei = parseEther(amountIUSD);
      const approveHash = await sendTx(config.mockIUSDAddress,
        encodeFunctionData({ abi: MOCK_IUSD_ABI, functionName: 'approve', args: [config.sessionVaultAddress, amountWei] }));
      updateStep(0, { status: 'success', txHash: approveHash });
      updateStep(1, { status: 'pending' });
      const depositHash = await sendTx(config.sessionVaultAddress,
        encodeFunctionData({ abi: SESSION_VAULT_ABI, functionName: 'createSession', args: [amountWei, BigInt(durationHours * 3600)] }));
      updateStep(1, { status: 'success', txHash: depositHash });
      refetchBalance();
      queryClient.invalidateQueries({ queryKey: ['profile'] });
    } catch (e: any) {
      setError(e.message);
      setSteps(prev => prev.map(s => s.status === 'pending' ? { ...s, status: 'error', error: e.message } : s));
    } finally { setLoading(false); }
  }, [sendTx, refetchBalance, queryClient]);

  // Withdraw: close active session
  const closeSession = useCallback(async () => {
    if (!address) return;
    setLoading(true); setError(null);
    setSteps([{ label: 'Finding active session...', status: 'pending' }]);
    try {
      const sessionIds = await publicClient.readContract({
        address: config.sessionVaultAddress, abi: SESSION_VAULT_ABI,
        functionName: 'getUserSessions', args: [address as `0x${string}`],
      }) as bigint[];
      if (!sessionIds.length) throw new Error('No sessions found');
      // Find latest active session
      let activeId: bigint | null = null;
      for (let i = sessionIds.length - 1; i >= 0; i--) {
        const s = await publicClient.readContract({
          address: config.sessionVaultAddress, abi: SESSION_VAULT_ABI,
          functionName: 'getSession', args: [sessionIds[i]],
        }) as any;
        if (s.active) { activeId = sessionIds[i]; break; }
      }
      if (!activeId) throw new Error('No active session');
      updateStep(0, { label: 'Closing session...', status: 'pending' });
      const hash = await sendTx(config.sessionVaultAddress,
        encodeFunctionData({ abi: SESSION_VAULT_ABI, functionName: 'closeSession', args: [activeId] }));
      updateStep(0, { status: 'success', txHash: hash, label: 'Session closed — iUSD returned' });
      refetchBalance();
      queryClient.invalidateQueries({ queryKey: ['profile'] });
    } catch (e: any) {
      setError(e.message);
      updateStep(0, { status: 'error', error: e.message });
    } finally { setLoading(false); }
  }, [address, sendTx, refetchBalance, queryClient]);

  const clearSteps = useCallback(() => { setSteps([]); setError(null); }, []);

  return { claimFaucet, approveAndDeposit, closeSession, clearSteps, loading, error, steps, iusdBalance, connected: !!address, address };
}
