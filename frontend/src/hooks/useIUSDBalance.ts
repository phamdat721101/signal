import { useQuery } from '@tanstack/react-query';
import { createPublicClient, formatEther, http } from 'viem';
import { usePrivy } from '@privy-io/react-auth';
import { config } from '../config';

const BALANCE_OF_ABI = [
  { name: 'balanceOf', type: 'function', inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }], stateMutability: 'view' },
] as const;

const SESSION_VAULT_ABI = [
  { name: 'getUserSessions', type: 'function', inputs: [{ name: 'user', type: 'address' }], outputs: [{ name: '', type: 'uint256[]' }], stateMutability: 'view' },
  { name: 'getSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }], outputs: [{ name: '', type: 'tuple', components: [{ name: 'depositor', type: 'address' }, { name: 'depositAmount', type: 'uint256' }, { name: 'remainingBalance', type: 'uint256' }, { name: 'totalRedeemed', type: 'uint256' }, { name: 'voucherCount', type: 'uint256' }, { name: 'createdAt', type: 'uint256' }, { name: 'expiresAt', type: 'uint256' }, { name: 'active', type: 'bool' }] }], stateMutability: 'view' },
] as const;

const publicClient = createPublicClient({ chain: config.chain, transport: http() });

function bech32ToHex(addr: string): `0x${string}` {
  const CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
  const data = addr.slice(addr.lastIndexOf('1') + 1);
  const words = [...data].map(c => CHARSET.indexOf(c)).slice(0, -6);
  let bits = 0, value = 0;
  const bytes: number[] = [];
  for (const w of words) {
    value = (value << 5) | w;
    bits += 5;
    while (bits >= 8) { bits -= 8; bytes.push((value >> bits) & 0xff); }
  }
  return `0x${bytes.map(b => b.toString(16).padStart(2, '0')).join('')}` as `0x${string}`;
}

async function fetchSessionBalance(evmAddress: `0x${string}`): Promise<bigint> {
  const sessionIds = await publicClient.readContract({
    address: config.sessionVaultAddress, abi: SESSION_VAULT_ABI,
    functionName: 'getUserSessions', args: [evmAddress],
  }) as bigint[];
  const now = BigInt(Math.floor(Date.now() / 1000));
  let total = 0n;
  for (let i = sessionIds.length - 1; i >= 0; i--) {
    const s = await publicClient.readContract({
      address: config.sessionVaultAddress, abi: SESSION_VAULT_ABI,
      functionName: 'getSession', args: [sessionIds[i]],
    }) as any;
    if (s.active && s.expiresAt > now) total += s.remainingBalance;
  }
  return total;
}

export function useIUSDBalance() {
  const { user } = usePrivy();
  const initiaAddress = user?.wallet?.address || "";
  const evmAddress = initiaAddress ? bech32ToHex(initiaAddress) : undefined;

  const { data, isLoading } = useQuery({
    queryKey: ['iusd-balance', evmAddress],
    queryFn: async () => {
      if (!evmAddress) return { wallet: 0n, session: 0n };
      const [wallet, session] = await Promise.all([
        publicClient.readContract({
          address: config.mockIUSDAddress, abi: BALANCE_OF_ABI,
          functionName: 'balanceOf', args: [evmAddress],
        }) as Promise<bigint>,
        fetchSessionBalance(evmAddress),
      ]);
      return { wallet, session };
    },
    enabled: !!evmAddress && config.paymentEnabled,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  return {
    walletBalance: data?.wallet ?? 0n,
    sessionBalance: data?.session ?? 0n,
    walletFormatted: formatEther(data?.wallet ?? 0n),
    sessionFormatted: formatEther(data?.session ?? 0n),
    isLoading,
  };
}
