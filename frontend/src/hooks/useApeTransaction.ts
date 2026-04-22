import { useState, useCallback } from 'react';
import { encodeFunctionData, keccak256, toHex } from 'viem';
import { useWallets } from '@privy-io/react-auth';
import { config } from '../config';
import type { Card } from './useCards';

const CREATE_SIGNAL_ABI = [
  {
    type: 'function' as const,
    name: 'createSignal',
    inputs: [
      { name: 'asset', type: 'address' },
      { name: 'isBull', type: 'bool' },
      { name: 'confidence', type: 'uint8' },
      { name: 'targetPrice', type: 'uint256' },
      { name: 'entryPrice', type: 'uint256' },
    ],
    outputs: [{ name: '', type: 'uint256' }],
    stateMutability: 'nonpayable' as const,
  },
] as const;

function symbolToAddress(symbol: string): `0x${string}` {
  const known: Record<string, string> = {
    BTC: '0x0000000000000000000000000000000000000001',
    ETH: '0x0000000000000000000000000000000000000002',
    INIT: '0x0000000000000000000000000000000000000003',
  };
  const upper = symbol.toUpperCase();
  if (known[upper]) return known[upper] as `0x${string}`;
  const hash = keccak256(toHex(upper));
  return `0x${hash.slice(2, 42)}` as `0x${string}`;
}

export function useApeTransaction() {
  const { wallets } = useWallets();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apeOnChain = useCallback(async (card: Card): Promise<string | null> => {
    const wallet = wallets.find(w => w.walletClientType === 'privy');
    if (!wallet || config.contractAddress === '0x0000000000000000000000000000000000000000') return null;

    setIsLoading(true);
    setError(null);
    try {
      try { await wallet.switchChain(config.chain.id); } catch { /* already on chain */ }
      const provider = await wallet.getEthereumProvider();
      const isBull = card.verdict === 'APE';
      const confidence = Math.min(95, Math.max(50, card.risk_score || 70));
      const entryWei = BigInt(Math.round(card.price * 1e18));
      const targetWei = isBull
        ? BigInt(Math.round(card.price * 1.015 * 1e18))
        : BigInt(Math.round(card.price * 0.985 * 1e18));

      const data = encodeFunctionData({
        abi: CREATE_SIGNAL_ABI,
        functionName: 'createSignal',
        args: [symbolToAddress(card.token_symbol), isBull, confidence, targetWei, entryWei],
      });

      const txHash = await provider.request({
        method: 'eth_sendTransaction',
        params: [{ from: wallet.address, to: config.contractAddress, data, gas: '0x7A120', gasPrice: '0x0' }],
      }) as string;

      setIsLoading(false);
      return txHash;
    } catch (e: any) {
      setError(e.message || 'Transaction failed');
      setIsLoading(false);
      return null;
    }
  }, [wallets]);

  return { apeOnChain, isLoading, error };
}
