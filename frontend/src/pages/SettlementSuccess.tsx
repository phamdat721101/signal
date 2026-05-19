import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { createPublicClient, http } from 'viem';
import { config, explorerTxUrl } from '../config';
import { useWallet } from '../hooks/useWallet';

/**
 * SettlementSuccess — landing page after a multi-call swipe-session settle.
 *
 * Reads ConvictionEngine.getReputation(user) to confirm the on-chain delta
 * landed. Shows the multi-call tx in the explorer. Pure read-side; no writes.
 */

const CONVICTION_ABI = [
  {
    name: 'getReputation', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'user', type: 'address' }],
    outputs: [{
      name: '', type: 'tuple',
      components: [
        { name: 'totalConvictions', type: 'uint256' },
        { name: 'correctCalls', type: 'uint256' },
        { name: 'reputationScore', type: 'int256' },
        { name: 'currentStreak', type: 'uint256' },
        { name: 'bestStreak', type: 'uint256' },
        { name: 'totalConvictionPoints', type: 'uint256' },
      ],
    }],
  },
] as const;

interface Reputation {
  totalConvictions: bigint;
  correctCalls: bigint;
  reputationScore: bigint;
  currentStreak: bigint;
  bestStreak: bigint;
  totalConvictionPoints: bigint;
}

const publicClient = createPublicClient({ chain: config.chain, transport: http() });

export default function SettlementSuccess() {
  const { txHash } = useParams<{ txHash: string }>();
  const { address } = useWallet();
  const [rep, setRep] = useState<Reputation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const convictionEngineAddr =
    (import.meta as any).env?.VITE_CONVICTION_ENGINE_ADDRESS as `0x${string}` | undefined;

  useEffect(() => {
    if (!address || !convictionEngineAddr ||
        convictionEngineAddr === '0x0000000000000000000000000000000000000000') {
      return;
    }
    publicClient
      .readContract({
        address: convictionEngineAddr,
        abi: CONVICTION_ABI,
        functionName: 'getReputation',
        args: [address as `0x${string}`],
      })
      .then(r => setRep(r as Reputation))
      .catch(e => setError(e?.message || 'reputation read failed'));
  }, [address, convictionEngineAddr]);

  return (
    <div className="max-w-md mx-auto px-4 py-8 text-white">
      <h1 className="text-2xl font-bold mb-2">Session settled</h1>
      <p className="text-sm text-gray-400 mb-6">
        Your swipes are now on-chain — every APE and FADE recorded as a
        ConvictionEngine commitment, plus tradeable APEs as Signals.
      </p>

      {txHash && (
        <a
          href={explorerTxUrl(txHash)}
          target="_blank"
          rel="noreferrer"
          className="block w-full text-center py-3 mb-6 rounded-lg
                     bg-emerald-500 hover:bg-emerald-400 text-black font-semibold"
        >
          View settlement tx on Initia Scan ↗
        </a>
      )}

      {error && (
        <p className="text-red-400 text-sm mb-4">Reputation read failed: {error}</p>
      )}

      {rep ? (
        <div className="space-y-2 bg-zinc-900 p-4 rounded-lg">
          <Row label="Total convictions" value={rep.totalConvictions.toString()} />
          <Row label="Correct calls" value={rep.correctCalls.toString()} />
          <Row label="Reputation score" value={rep.reputationScore.toString()} />
          <Row label="Current streak" value={rep.currentStreak.toString()} />
          <Row label="Best streak" value={rep.bestStreak.toString()} />
        </div>
      ) : (
        !error && <p className="text-gray-500 text-sm">Loading on-chain reputation…</p>
      )}

      <Link
        to="/"
        className="block w-full text-center py-3 mt-6 rounded-lg
                   border border-zinc-700 hover:border-zinc-500 text-white"
      >
        Back to feed
      </Link>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-gray-400">{label}</span>
      <span className="font-mono text-white">{value}</span>
    </div>
  );
}
