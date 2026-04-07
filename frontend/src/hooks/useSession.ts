import { useState, useCallback } from 'react';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { createPublicClient, encodeFunctionData, http, parseEther } from 'viem';
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
  { name: 'getUserSessions', type: 'function', inputs: [{ name: 'user', type: 'address' }], outputs: [{ name: '', type: 'uint256[]' }], stateMutability: 'view' },
  { name: 'getSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }], outputs: [{ name: '', type: 'tuple', components: [{ name: 'depositor', type: 'address' }, { name: 'depositAmount', type: 'uint256' }, { name: 'remainingBalance', type: 'uint256' }, { name: 'totalRedeemed', type: 'uint256' }, { name: 'voucherCount', type: 'uint256' }, { name: 'createdAt', type: 'uint256' }, { name: 'expiresAt', type: 'uint256' }, { name: 'active', type: 'bool' }] }], stateMutability: 'view' },
  { name: 'payFromSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }, { name: 'amount', type: 'uint256' }, { name: 'serviceId', type: 'string' }], outputs: [], stateMutability: 'nonpayable' },
] as const;

export type TxStep = {
  label: string;
  status: 'pending' | 'success' | 'error' | 'idle';
  txHash?: string;
  error?: string;
};

type SessionInfo = {
  sessionId: number;
  remainingBalance: bigint;
  expiresAt: bigint;
  active: boolean;
};

const publicClient = createPublicClient({ chain: config.chain, transport: http() });

/** Decode bech32 initia address to 0x hex address. */
function bech32ToHex(addr: string): `0x${string}` {
  const CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
  const sepIdx = addr.lastIndexOf('1');
  const data = addr.slice(sepIdx + 1);
  const values = [...data].map(c => CHARSET.indexOf(c));
  const words = values.slice(0, -6); // drop checksum
  let bits = 0, value = 0;
  const bytes: number[] = [];
  for (const w of words) {
    value = (value << 5) | w;
    bits += 5;
    while (bits >= 8) {
      bits -= 8;
      bytes.push((value >> bits) & 0xff);
    }
  }
  return `0x${bytes.map(b => b.toString(16).padStart(2, '0')).join('')}` as `0x${string}`;
}

export function useSession() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<TxStep[]>([]);
  const { initiaAddress, requestTxBlock } = useInterwovenKit();
  const queryClient = useQueryClient();

  const evmAddress = initiaAddress ? bech32ToHex(initiaAddress) : undefined;

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

  const findActiveSession = useCallback(async (minBalance: bigint): Promise<SessionInfo | null> => {
    if (!evmAddress) return null;
    try {
      const sessionIds = await publicClient.readContract({
        address: config.sessionVaultAddress,
        abi: SESSION_VAULT_ABI,
        functionName: 'getUserSessions',
        args: [evmAddress],
      }) as bigint[];
      // Check sessions in reverse (newest first)
      for (let i = sessionIds.length - 1; i >= 0; i--) {
        const session = await publicClient.readContract({
          address: config.sessionVaultAddress,
          abi: SESSION_VAULT_ABI,
          functionName: 'getSession',
          args: [sessionIds[i]],
        }) as any;
        const now = BigInt(Math.floor(Date.now() / 1000));
        if (session.active && session.expiresAt > now && session.remainingBalance >= minBalance) {
          return {
            sessionId: Number(sessionIds[i]),
            remainingBalance: session.remainingBalance,
            expiresAt: session.expiresAt,
            active: true,
          };
        }
      }
    } catch (e) {
      console.error('[Session] Failed to find active session:', e);
    }
    return null;
  }, [evmAddress]);

  const payForService = useCallback(async (sessionId: number, amountWei: bigint, serviceId: string): Promise<string | undefined> => {
    const data = encodeFunctionData({
      abi: SESSION_VAULT_ABI,
      functionName: 'payFromSession',
      args: [BigInt(sessionId), amountWei, serviceId],
    });
    return sendTx(config.sessionVaultAddress, data);
  }, [sendTx]);

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

  return { approveAndDeposit, claimFaucet, clearSteps, findActiveSession, payForService, loading, error, steps, connected: !!initiaAddress, evmAddress };
}
