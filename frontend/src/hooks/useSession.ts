import { useState, useCallback, useEffect } from 'react';
// import { usePrivy, useWallets } from '@privy-io/react-auth';
import { createPublicClient, encodeFunctionData, http, parseEther, formatEther } from 'viem';
import { config, normalizeAddress } from '../config';
import { useQueryClient, useQuery } from '@tanstack/react-query';
import { useWallet } from './useWallet';

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
  const { address: rawAddress, sendTx } = useWallet();
  const address = normalizeAddress(rawAddress);
  const queryClient = useQueryClient();

  const updateStep = (index: number, update: Partial<TxStep>) => {
    setSteps(prev => prev.map((s, i) => i === index ? { ...s, ...update } : s));
  };

  // ── iUSD faucet cooldown (5min — mirrors backend FAUCET_COOLDOWN). UX-only; backend still enforces. ──
  const FAUCET_COOLDOWN_MS = 300_000;
  const cooldownKey = address ? `iusd_faucet_last_${address.toLowerCase()}` : '';
  const [iusdCooldownSeconds, setIusdCooldownSeconds] = useState(0);
  useEffect(() => {
    if (!cooldownKey || typeof window === 'undefined') { setIusdCooldownSeconds(0); return; }
    const tick = () => {
      const last = Number(window.localStorage.getItem(cooldownKey) || 0);
      const remaining = Math.max(0, Math.ceil((last + FAUCET_COOLDOWN_MS - Date.now()) / 1000));
      setIusdCooldownSeconds(remaining);
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [cooldownKey]);
  const mockIUSDConfigured = config.mockIUSDAddress !== '0x0000000000000000000000000000000000000000';

  // Read iUSD wallet balance (free balance, not locked in vault).
  // Distinct query key from useIUSDBalance (['iusd-balance']) which returns
  // a richer {wallet, session} shape — sharing keys was causing cache
  // collisions where one consumer's queryFn output broke the other consumer.
  const { data: iusdBalance, refetch: refetchBalance } = useQuery({
    queryKey: ['iusd-wallet', address],
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

  // Send tx via wagmi (provided by useWallet hook)

  // Faucet: use backend endpoint (deployer mints to user — most reliable)
  const claimFaucet = useCallback(async () => {
    if (!address) return;
    setLoading(true); setError(null);
    setSteps([{ label: 'Claim 1000 iUSD from faucet', status: 'pending' }]);
    try {
      const resp = await fetch(`${config.backendUrl}/api/payment/faucet?address=${address}`, { method: 'POST' });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        // Friendly error mapping from FastAPI HTTPException(detail=...)
        const detail = data?.detail || resp.statusText || 'Faucet failed';
        const friendly =
          resp.status === 429 ? `Cooldown — ${detail}` :
          resp.status === 400 ? `Faucet unavailable — ${detail}` :
          resp.status === 403 ? 'Faucet disabled on this network' :
          `Network error — ${detail}`;
        throw new Error(friendly);
      }
      updateStep(0, { status: 'success', txHash: data.txHash });
      if (cooldownKey && typeof window !== 'undefined') {
        window.localStorage.setItem(cooldownKey, String(Date.now()));
        setIusdCooldownSeconds(Math.ceil(FAUCET_COOLDOWN_MS / 1000));
      }
      refetchBalance();
    } catch (e: any) {
      setError(e.message);
      updateStep(0, { status: 'error', error: e.message });
    } finally { setLoading(false); }
  }, [address, refetchBalance, cooldownKey]);

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
      // Wait for the deposit tx to be mined before telling the backend.
      // Without this, /api/energy/refill races the receipt and gets 403
      // (tx_not_found_or_failed) because eth_getTransactionReceipt returns
      // null for un-mined hashes. Bounded by viem's default 60s.
      await publicClient.waitForTransactionReceipt({ hash: depositHash as `0x${string}` });
      updateStep(1, { status: 'success', txHash: depositHash });
      // Backend verifies the receipt + SessionCreated event (idempotent on
      // tx_hash) before resetting daily_swipes. Fire-and-forget — UI updates
      // via the energy-query invalidation below.
      fetch(`${config.backendUrl}/api/energy/refill`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address, tx_hash: depositHash }),
      }).catch(() => { /* best-effort; backend reconciles via /api/energy GET on next poll */ });
      refetchBalance();
      queryClient.invalidateQueries({ queryKey: ['profile'] });
      queryClient.invalidateQueries({ queryKey: ['energy'] });
      queryClient.invalidateQueries({ queryKey: ['iusd-balance'] });
    } catch (e: any) {
      setError(e.message);
      setSteps(prev => prev.map(s => s.status === 'pending' ? { ...s, status: 'error', error: e.message } : s));
    } finally { setLoading(false); }
  }, [sendTx, refetchBalance, queryClient, address]);

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
      queryClient.invalidateQueries({ queryKey: ['energy'] });
      queryClient.invalidateQueries({ queryKey: ['iusd-balance'] });
    } catch (e: any) {
      setError(e.message);
      updateStep(0, { status: 'error', error: e.message });
    } finally { setLoading(false); }
  }, [address, sendTx, refetchBalance, queryClient]);

  const clearSteps = useCallback(() => { setSteps([]); setError(null); }, []);

  return {
    claimFaucet, approveAndDeposit, closeSession, clearSteps,
    loading, error, steps, iusdBalance,
    iusdCooldownSeconds, mockIUSDConfigured,
    connected: !!address, address,
  };
}
