import { useCallback, useState } from 'react';
import { encodeFunctionData, keccak256, toHex } from 'viem';
import { useSwitchChain } from 'wagmi';
import { config } from '../config';
import { useWallet } from './useWallet';
import type { Card } from './useCards';

/**
 * useSummonTransaction — chain-aware APE handler.
 *
 * Today this is the Initia `createSignal` path: convert a card swipe
 * into one signed transaction on Initia EVM. When a v4-hook chain is
 * wired up, add a single branch keyed off `card.chain_id` — same
 * shape, no other surface needs to change.
 *
 * SOLID:
 *   - Single responsibility: convert a card swipe into one settled tx.
 *   - Open/closed: adding a new chain = adding one branch + one backend route, no UI change.
 */

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

export interface SummonResult {
  txHash: string;
  chainId: number;
}

export interface UseSummonTransaction {
  summon: (card: Card) => Promise<SummonResult | null>;
  isLoading: boolean;
  step: string | null;
  error: string | null;
  reset: () => void;
}

export function useSummonTransaction(): UseSummonTransaction {
  const { sendTx, isConnected, chainId, address } = useWallet();
  const { switchChainAsync } = useSwitchChain();
  const [isLoading, setIsLoading] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setIsLoading(false); setStep(null); setError(null);
  }, []);

  const summon = useCallback(async (card: Card): Promise<SummonResult | null> => {
    if (!isConnected || !address) { setError('Connect wallet first'); return null; }

    const targetChain = (card as { chain_id?: number }).chain_id ?? chainId ?? config.chain.id;
    setError(null); setIsLoading(true);

    try {
      if (chainId !== targetChain) {
        setStep('Switching network');
        await switchChainAsync({ chainId: targetChain });
      }

      if (config.contractAddress === '0x0000000000000000000000000000000000000000') {
        throw new Error('SignalRegistry not deployed on this chain');
      }

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

      setStep('Recording on-chain');
      const txHash = await sendTx(config.contractAddress, data);

      setIsLoading(false); setStep(null);
      return { txHash, chainId: targetChain };
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Summon failed');
      setIsLoading(false); setStep(null);
      return null;
    }
  }, [chainId, isConnected, address, sendTx, switchChainAsync]);

  return { summon, isLoading, step, error, reset };
}
