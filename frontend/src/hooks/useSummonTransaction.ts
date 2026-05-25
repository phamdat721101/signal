import { useCallback, useState } from 'react';
import { encodeFunctionData, keccak256, toHex } from 'viem';
import { useSwitchChain } from 'wagmi';
import { config, isXLayer } from '../config';
import { useWallet } from './useWallet';
import type { Card } from './useCards';

/**
 * useSummonTransaction — chain-aware APE handler.
 *
 * Dispatches by the card's chain (not the wallet's currently-connected chain):
 *
 *   card.chain_id == 1952 / 196  → X Layer "summon" path:
 *     1. ensureChain(1952) — switchChainAsync if needed
 *     2. POST /api/cards/{id}/play  → returns {calls: [approveOKB, approveUSDC, playCard]}
 *     3. execute calls sequentially via useWallet.sendTx
 *
 *   default                       → Initia createSignal path (existing).
 *
 * Default chain resolution (no DB migration required):
 *   1. Use card.chain_id if explicitly set.
 *   2. Else, if VITE_XLAYER_ROUTER_ADDRESS is configured, default to X Layer testnet (1952).
 *   3. Else, fall back to Initia.
 *
 * SOLID:
 *   - Single responsibility: convert a card swipe into one settled tx.
 *   - Open/closed: adding a new chain = adding one branch + one backend route, no UI change.
 *   - No premature abstraction (no useSigner extraction yet — see UPGRADE doc §4.1).
 *
 * Note: testrpc.xlayer.tech serves chain 1952 (Terigon), not the chain-195
 * RPC documented on chainlist.org. Replaces useApeTransaction.ts.
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
  /** Last call index that succeeded (0..calls.length-1). For X Layer multi-call. */
  completedSteps?: number;
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

    const cardChainId = (card as any).chain_id;
    // Routing rule: wallet's currently-selected chain decides the flow.
    //  — On X Layer (1952/196): SignalCardRouter v4-hook LP open path.
    //  — Anywhere else (Initia default): legacy createSignal path.
    // Cards CAN override via card.chain_id but the standard pattern is
    // "user picks the network in the header pill, that's the active flow."
    const targetChain = cardChainId ?? chainId ?? config.chain.id;
    setError(null); setIsLoading(true);

    try {
      // ── Chain switch if needed ───────────────────────────────────────
      if (chainId !== targetChain) {
        setStep('Switching to ' + (isXLayer(targetChain) ? 'X Layer' : 'Initia'));
        await switchChainAsync({ chainId: targetChain });
      }

      // ── X Layer path: backend bundle (approvals + playCard) ──────────
      if (isXLayer(targetChain)) {
        setStep('Preparing summon');
        const resp = await fetch(`${config.backendUrl}/api/cards/${card.id}/play`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ address }),
        });
        if (!resp.ok) {
          let msg = `Backend: ${resp.status}`;
          try { const j = await resp.json(); if (j?.detail) msg = String(j.detail); } catch {}
          throw new Error(msg);
        }
        const bundle = await resp.json() as {
          calls: Array<{ to: string; data: string }>;
        };

        // Execute calls sequentially. The router's playCard is the last call.
        // If approve already exists (allowance >= amount), wallet will skip the prompt.
        // Pass targetChain so wagmi signs for X Layer (1952), not Initia.
        let lastTx = '';
        for (let i = 0; i < bundle.calls.length; i++) {
          const isFinal = i === bundle.calls.length - 1;
          setStep(isFinal ? 'Summoning' : `Approving (${i + 1}/${bundle.calls.length - 1})`);
          lastTx = await sendTx(bundle.calls[i].to, bundle.calls[i].data, targetChain);
        }

        setIsLoading(false); setStep(null);
        return { txHash: lastTx, chainId: targetChain, completedSteps: bundle.calls.length };
      }

      // ── Default Initia createSignal path ─────────────────────────────
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
    } catch (e: any) {
      setError(e?.message || 'Summon failed');
      setIsLoading(false); setStep(null);
      return null;
    }
  }, [chainId, isConnected, address, sendTx, switchChainAsync]);

  return { summon, isLoading, step, error, reset };
}
