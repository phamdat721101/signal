/**
 * /somnia/prediction — Kinetic v3 cross-chain prediction page.
 *
 * What this page does:
 *  - Renders prophecy cards filtered to `cross_chain_ready=true`
 *  - Lets a user holding USDC on Arbitrum Sepolia (testnet) or Arbitrum
 *    mainnet swipe APE/FADE in a single signature.
 *  - Surfaces three on-chain proof links (Arbiscan + Somnscan + prophecy
 *    market) inline once the swipe lands — the verification surface for
 *    Somnia core team review.
 *  - Testnet build only: shows a "Get test USDC" faucet button that calls
 *    `MockUSDC.mint(user, 10e6)` so reviewers don't have to chase a faucet.
 *
 * SOLID:
 *  - SRP: page-level layout + data-fetch + chain-selector. Per-card swipe
 *    UX lives in `CrossChainSwipeButton`.
 *  - OCP: chain options are a flat array; new origins (Base, Optimism, …)
 *    = one row.
 */
import { useEffect, useState } from 'react';
import { useAccount, useWriteContract } from 'wagmi';
import CrossChainSwipeButton from '../../components/CrossChainSwipeButton';
import type { Card } from '../../hooks/useCards';

const NETWORK         = (import.meta.env.VITE_KINETIC_NETWORK as 'testnet' | 'mainnet') || 'testnet';
const IS_TESTNET      = NETWORK === 'testnet';
const ARBITRUM_CHAIN  = IS_TESTNET ? 421614 : 42161;
const ARBITRUM_USDC   = (IS_TESTNET
  ? '0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d'   // Circle Arb-Sepolia USDC
  : '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'   // Arbitrum mainnet USDC
) as `0x${string}`;
const FAUCET_USDC     = (import.meta.env.VITE_SOMNIA_USDC_ADDRESS || '') as `0x${string}` | '';

const ORIGIN_OPTIONS = [
  { id: ARBITRUM_CHAIN, label: IS_TESTNET ? 'Arbitrum Sepolia' : 'Arbitrum' },
];

const API_URL = import.meta.env.VITE_BACKEND_URL || '';

const ERC20_MINT_ABI = [{
  type: 'function',
  name: 'mint',
  stateMutability: 'nonpayable',
  inputs: [
    { name: 'to',     type: 'address' },
    { name: 'amount', type: 'uint256' },
  ],
  outputs: [],
}] as const;

export default function CrossChainSwipe() {
  const { address, isConnected } = useAccount();
  const [originChainId, setOriginChainId] = useState(ARBITRUM_CHAIN);
  const [cards, setCards]   = useState<Card[] | null>(null);
  const [loading, setLoading] = useState(true);

  // Fetch cards once on mount. Filters cross_chain_ready=true server-side.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_URL}/api/cards?cross_chain_ready=true&limit=10`);
        if (cancelled) return;
        if (r.ok) {
          const j = await r.json();
          setCards(Array.isArray(j) ? j : (j.cards || []));
        } else {
          setCards([]);
        }
      } catch {
        setCards([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="container mx-auto max-w-3xl py-6 px-4 space-y-5">
      <header>
        <h1 className="text-2xl font-bold text-white">Cross-Chain Prophecy Cards</h1>
        <p className="text-sm text-zinc-400 mt-1">
          Swipe a prediction card with USDC from Arbitrum. One signature, ~30–90 seconds, bet binds on Somnia.
        </p>
        <p className="text-[11px] text-zinc-500 mt-1">
          Network: <span className="font-mono text-zinc-300">{NETWORK}</span> · Origin chain: <span className="font-mono text-zinc-300">{originChainId}</span>
        </p>
      </header>

      <ChainSelector value={originChainId} onChange={setOriginChainId} />
      {IS_TESTNET && <TestnetFaucet usdc={FAUCET_USDC} userAddress={address} />}

      <main>
        {loading && <p className="text-zinc-400">Loading cards…</p>}
        {!loading && cards && cards.length === 0 && (
          <p className="text-zinc-500 text-sm">
            No cross-chain-ready cards right now. Card pipeline tags new ones every minute — check back shortly.
          </p>
        )}
        {!loading && cards && cards.length > 0 && (
          <div className="space-y-4">
            {cards.map((c) => (
              <PredictionCardRow
                key={c.id}
                card={c}
                fromChain={originChainId}
                fromToken={ARBITRUM_USDC}
                userAddress={isConnected ? (address as `0x${string}`) : undefined}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function ChainSelector({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm text-zinc-300">
      <span>Origin chain:</span>
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="bg-zinc-900 border border-white/10 rounded px-2 py-1"
      >
        {ORIGIN_OPTIONS.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

function TestnetFaucet({ usdc, userAddress }: { usdc: `0x${string}` | ''; userAddress: string | undefined }) {
  const { writeContractAsync, isPending } = useWriteContract();
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!usdc || !userAddress) return null;

  async function mint() {
    try {
      setErr(null);
      await writeContractAsync({
        address: usdc as `0x${string}`,
        abi: ERC20_MINT_ABI,
        functionName: 'mint',
        args: [userAddress as `0x${string}`, 10_000_000n],   // 10 mUSDC (6-dec)
        chainId: 50312,
      });
      setDone(true);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Faucet failed');
    }
  }

  return (
    <div className="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-sm flex items-center justify-between">
      <span className="text-amber-200">Testnet — claim 10 mUSDC for cross-chain swipe demo</span>
      <button
        onClick={mint}
        disabled={isPending || done}
        className="px-3 py-1 rounded bg-amber-500 text-black text-xs font-bold disabled:opacity-50"
        aria-label="Mint 10 test USDC for cross-chain swipe demo"
      >
        {done ? 'Minted ✓' : isPending ? 'Minting…' : 'Get test USDC'}
      </button>
      {err && <span className="ml-2 text-xs text-rose-400">{err}</span>}
    </div>
  );
}

function PredictionCardRow({
  card, fromChain, fromToken, userAddress,
}: {
  card: Card;
  fromChain: number;
  fromToken: `0x${string}`;
  userAddress: `0x${string}` | undefined;
}) {
  // Use `min_swipe_stake_usdc` from the card row when present; default to $0.10 testnet floor.
  const stake = BigInt((card as Card & { min_swipe_stake_usdc?: number }).min_swipe_stake_usdc || 100_000);
  const marketId = Number((card as Card & { prophecy_market_id?: number }).prophecy_market_id || 0);
  const sym = card.token_symbol || 'BTC';
  const ctx = (card.hook || card.token_name || sym).slice(0, 200);

  return (
    <article className="rounded-xl border border-white/10 bg-zinc-900 p-4">
      <header className="flex items-baseline justify-between mb-2">
        <h2 className="font-bold text-white text-lg">{sym}</h2>
        <span className="text-[11px] text-zinc-500 font-mono">market #{marketId}</span>
      </header>
      <p className="text-sm text-zinc-300 mb-3 line-clamp-3">{card.hook || card.token_name}</p>
      <div className="grid grid-cols-2 gap-3">
        <CrossChainSwipeButton
          cardId={card.id}
          prophecyMarketId={marketId}
          symbol={sym}
          context={ctx}
          swipeStakeUsdc={stake}
          fromChain={fromChain}
          fromToken={fromToken}
          userAddress={userAddress}
          verdict="APE"
        />
        <CrossChainSwipeButton
          cardId={card.id}
          prophecyMarketId={marketId}
          symbol={sym}
          context={ctx}
          swipeStakeUsdc={stake}
          fromChain={fromChain}
          fromToken={fromToken}
          userAddress={userAddress}
          verdict="FADE"
        />
      </div>
    </article>
  );
}
