/**
 * useERC20Balance — generic ERC20 `balanceOf` reader.
 *
 * Single Responsibility: pull an ERC20 balance for the connected wallet on a
 * specific chain (default: card.chain_id, fallback: wallet's current chain).
 * No formatting beyond returning a `bigint` and a string-formatted version
 * for display. UI components decide how to render.
 *
 * Why this exists: `useIUSDBalance` is hardcoded to MockIUSD on Initia EVM.
 * The LP Configurator needs to display a token's balance on whichever chain
 * the pool lives on (Base, Polygon, Arbitrum, …). This is the chain-aware
 * primitive the project lacked.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { createPublicClient, formatUnits, http, type Address } from 'viem';
import { normalizeAddress } from '../config';
import { useWallet } from './useWallet';

const ERC20_ABI = [
  {
    name: 'balanceOf', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }],
    outputs: [{ type: 'uint256' }],
  },
] as const;

// Public read-only RPCs by chain id. Add new chains by appending one entry.
// All come from public, no-key endpoints commonly used by viem/wagmi.
const RPC_BY_CHAIN: Record<number, string> = {
  1: 'https://eth.llamarpc.com',
  10: 'https://mainnet.optimism.io',
  56: 'https://bsc-dataseed.bnbchain.org',
  137: 'https://polygon-rpc.com',
  8453: 'https://mainnet.base.org',
  42161: 'https://arb1.arbitrum.io/rpc',
  43114: 'https://api.avax.network/ext/bc/C/rpc',
  59144: 'https://rpc.linea.build',
};

export interface UseERC20BalanceResult {
  raw: bigint;
  formatted: string;
  isLoading: boolean;
}

export function useERC20Balance(
  tokenAddress: string | undefined,
  chainId: number | undefined,
  decimals: number = 18
): UseERC20BalanceResult {
  const { address } = useWallet();
  const evmAddress = address ? (normalizeAddress(address) as Address) : undefined;

  const rpcUrl = chainId ? RPC_BY_CHAIN[chainId] : undefined;

  const client = useMemo(() => {
    if (!rpcUrl) return null;
    return createPublicClient({ transport: http(rpcUrl) });
  }, [rpcUrl]);

  const { data, isLoading } = useQuery({
    queryKey: ['erc20-balance', tokenAddress, chainId, evmAddress],
    enabled: !!evmAddress && !!tokenAddress && !!client,
    staleTime: 15_000,
    queryFn: async (): Promise<bigint> => {
      if (!client || !tokenAddress || !evmAddress) return 0n;
      try {
        return (await client.readContract({
          address: tokenAddress as Address,
          abi: ERC20_ABI,
          functionName: 'balanceOf',
          args: [evmAddress],
        })) as bigint;
      } catch {
        return 0n;
      }
    },
  });

  const raw = data ?? 0n;
  return {
    raw,
    formatted: formatUnits(raw, decimals),
    isLoading,
  };
}
