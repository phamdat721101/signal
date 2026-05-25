import { useEffect, useState } from 'react';
import { useSummonTransaction } from '../hooks/useSummonTransaction';
import { explorerTxUrl, isCardTradeable } from '../config';
import type { Card } from '../hooks/useCards';

/**
 * SummonRitual — owns the entire summon ceremony for an X Layer card.
 *
 * Phases (SOLID single responsibility):
 *   1. confirm  — modal showing payoff narrative + Summon CTA
 *   2. signing  — driven by useSummonTransaction.step
 *   3. reveal   — 800ms keyframe animation on success (200ms with prefers-reduced-motion)
 *   4. done     — calls onSuccess and unmounts
 *
 * No new dependencies. Pure CSS keyframes inline below.
 */

const RARITY: Record<string, { name: string; color: string; emoji: string }> = {
  common:    { name: 'Common',    color: '#adaaaa', emoji: '🥉' },
  rare:      { name: 'Rare',      color: '#bf81ff', emoji: '✨' },
  epic:      { name: 'Epic',      color: '#ff7b3a', emoji: '⚔️' },
  legendary: { name: 'Legendary', color: '#ffd700', emoji: '👑' },
  mythic:    { name: 'Mythic',    color: '#ff0080', emoji: '🐉' },
};

interface Props {
  card: Card;
  open: boolean;
  onClose: () => void;
  onSuccess: (txHash: string, chainId: number) => void;
}

export default function SummonRitual({ card, open, onClose, onSuccess }: Props) {
  const { summon, isLoading, step, error, reset } = useSummonTransaction();
  const [phase, setPhase] = useState<'confirm' | 'reveal'>('confirm');
  const [tx, setTx] = useState<{ hash: string; chainId: number } | null>(null);

  useEffect(() => {
    if (!open) { setPhase('confirm'); setTx(null); reset(); }
  }, [open, reset]);

  // Auto-advance from reveal → done after 800ms (200ms with reduced-motion).
  useEffect(() => {
    if (phase !== 'reveal' || !tx) return;
    const reduceMotion = typeof window !== 'undefined'
      && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const ms = reduceMotion ? 200 : 800;
    const t = setTimeout(() => onSuccess(tx.hash, tx.chainId), ms);
    return () => clearTimeout(t);
  }, [phase, tx, onSuccess]);

  if (!open) return null;
  // Defense in depth: if a non-tradeable card slips past upstream gating,
  // close silently instead of rendering "$0.00–$0.00" and 400-ing on /play.
  if (!isCardTradeable(card)) { onClose(); return null; }

  const rarity = RARITY[card.rarity || 'common'] || RARITY.common;
  const isBull = card.verdict === 'APE';
  const target = isBull ? card.price * 1.015 : card.price * 0.985;
  const stop   = isBull ? card.price * 0.985 : card.price * 1.015;

  const handleSummon = async () => {
    const r = await summon(card);
    if (r) {
      setTx({ hash: r.txHash, chainId: r.chainId });
      setPhase('reveal');
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-6 bg-black/85 backdrop-blur-sm"
      onClick={phase === 'confirm' && !isLoading ? onClose : undefined}
    >
      {phase === 'confirm' && (
        <div
          className="bg-[#131313] rounded-2xl max-w-sm w-full overflow-hidden border"
          style={{ borderColor: `${rarity.color}33` }}
          onClick={e => e.stopPropagation()}
        >
          <div className="h-1.5" style={{ background: `linear-gradient(90deg, ${rarity.color}, ${rarity.color}88)` }} />
          <div className="p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="font-headline text-2xl font-black text-white">🔮 Summon ${card.token_symbol}?</h2>
              <span
                className="text-xs font-bold uppercase tracking-widest px-2 py-0.5 rounded"
                style={{ color: rarity.color, background: `${rarity.color}20` }}
              >
                {rarity.emoji} {rarity.name}
              </span>
            </div>
            <p className="text-sm text-[#adaaaa]">
              You'll lock <span className="text-white font-bold">~$50 OKB + ~$50 USDC</span> in a liquidity position.
            </p>
            <div className="bg-[#262626] rounded-xl p-3 space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-[#8eff71]">📈</span>
                <span className="text-[#adaaaa]">You earn fees while {card.token_symbol} trades</span>
                <span className="text-white font-bold ml-auto">${stop.toFixed(2)}–${target.toFixed(2)}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[#ff7166]">📉</span>
                <span className="text-[#adaaaa]">Take a loss if it closes outside</span>
                <span className="text-[#ff7166] font-bold ml-auto">±1.5%</span>
              </div>
              <div className="flex items-center gap-2">
                <span>⏱️</span>
                <span className="text-[#adaaaa]">Card expires</span>
                <span className="text-white ml-auto">in 24h</span>
              </div>
            </div>
            {error && <p className="text-xs text-[#ff7166]">{error}</p>}
            <div className="flex gap-2">
              <button
                onClick={onClose}
                disabled={isLoading}
                className="flex-1 bg-[#262626] text-[#adaaaa] font-headline font-bold py-3 rounded-lg disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSummon}
                disabled={isLoading}
                className="flex-1 ape-gradient text-[#0b5800] font-headline font-bold py-3 rounded-lg disabled:opacity-50 active:scale-95 transition-transform"
              >
                {isLoading ? (step || 'Summoning...') : '🔮 Summon'}
              </button>
            </div>
          </div>
        </div>
      )}

      {phase === 'reveal' && tx && (
        <div className="relative flex flex-col items-center gap-4 summon-reveal">
          <div
            className="summon-halo"
            style={{ '--halo': rarity.color } as React.CSSProperties}
          />
          <div className="text-7xl summon-card">{rarity.emoji}</div>
          <div
            className="font-headline text-3xl font-black"
            style={{ color: rarity.color }}
          >
            🐉 Summoned
          </div>
          <div className="text-xs text-[#adaaaa]">
            Tier <span className="font-bold" style={{ color: rarity.color }}>{rarity.name}</span> ·{' '}
            <a
              href={explorerTxUrl(tx.hash, tx.chainId)}
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              view tx
            </a>
          </div>
        </div>
      )}

      {/* Inline keyframes — no Tailwind config edit, no new files. */}
      <style>{`
        .summon-reveal {
          animation: summon-fade 200ms ease-out;
        }
        .summon-card {
          animation: summon-lift 800ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
        }
        .summon-halo {
          position: absolute;
          inset: -40px;
          border-radius: 9999px;
          background: radial-gradient(circle, var(--halo) 0%, transparent 60%);
          opacity: 0;
          animation: summon-halo 800ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
        }
        @keyframes summon-fade {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes summon-lift {
          0%   { transform: translate3d(0, 0, 0)        scale(0.6); opacity: 0; }
          25%  { transform: translate3d(0, -12px, 0)    scale(1.1); opacity: 1; }
          70%  { transform: translate3d(0, -8px, 0)     scale(1.0); opacity: 1; }
          100% { transform: translate3d(0, 0, 0)        scale(1.0); opacity: 1; }
        }
        @keyframes summon-halo {
          0%   { opacity: 0;   transform: scale(0.5); }
          40%  { opacity: 0.7; transform: scale(1.4); }
          100% { opacity: 0;   transform: scale(2.0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .summon-card, .summon-halo { animation-duration: 200ms !important; }
        }
      `}</style>
    </div>
  );
}
