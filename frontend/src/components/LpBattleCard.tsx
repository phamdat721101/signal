/**
 * LpBattleCard — feed-style card for a `card_type === 'pool'` row.
 *
 * Visual spec: lp-ui/lp_battle_card_feed/code.html (Kinetic Terminal —
 * neon green primary, glass panels, no 1px borders). Range overlay uses
 * the Balanced preset (k=1.0) as the visual default; the Configurator
 * lets the user change it.
 *
 * Single Responsibility: render the pool card + raise (open / deeplink)
 * via callbacks. No fetch logic, no transaction logic, no global state.
 */
import { useMemo } from 'react';
import type { Card } from '../hooks/useCards';
import { useLpRange } from '../hooks/useLpRange';

interface Props {
  card: Card;
  /** Tap "ADD LIQUIDITY" — opens LpConfigurator (parent wires it up). */
  onConfigure: () => void;
  /** Tap "VIEW STRATEGY" — same target as onConfigure but opens read-only. */
  onViewStrategy: () => void;
}

function fmtPct(n: number | undefined | null, digits = 1): string {
  if (n == null || !isFinite(n)) return '—';
  return `${n >= 0 ? '' : '-'}${Math.abs(n).toFixed(digits)}%`;
}

function fmtTvl(usd: number | undefined | null): string {
  if (!usd || !isFinite(usd)) return '—';
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(1)}M`;
  if (usd >= 1e3) return `$${(usd / 1e3).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

export default function LpBattleCard({ card, onConfigure, onViewStrategy }: Props) {
  const apy = card.price ?? 0;            // pool cards reuse `price` for APY
  const tvl = card.market_cap ?? 0;       // and `market_cap` for TVL
  const sym0 = card.token0_symbol || (card.token_symbol || '').split(/[-/]/)[0] || 'A';
  const sym1 = card.token1_symbol || (card.token_symbol || '').split(/[-/]/)[1] || 'B';

  // Range preview from σ_7d. Use a synthetic mid so the chart range box has
  // *something* to render even when no spot price is in the row. The
  // Configurator does the precise math via /lp-recipe.
  const sigma = card.volatility_7d_sigma ?? null;
  const { min, max } = useLpRange(1.0, sigma, 'balanced');
  const widthPct = useMemo(() => {
    if (!sigma) return 33;                // default 1/3 of chart
    const span = (max - min);             // around mid=1
    return Math.max(15, Math.min(80, span * 100));
  }, [sigma, min, max]);

  return (
    <div className="w-full max-w-sm mx-auto rounded-2xl overflow-hidden select-none">
      <div className="p-[2px] rounded-2xl bg-gradient-to-br from-[#8eff71]/40 via-[#8eff71]/10 to-[#bf81ff]/40">
        <div className="bg-[#0e0e0e] rounded-2xl overflow-hidden p-4 flex flex-col gap-4 relative">
          {/* Ambient corner glows */}
          <div className="absolute -top-10 -left-10 w-32 h-32 bg-[#8eff71]/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-10 -right-10 w-32 h-32 bg-[#bf81ff]/10 rounded-full blur-3xl pointer-events-none" />

          {/* Token-pair header */}
          <div className="flex justify-between items-center z-10">
            <div className="flex flex-col items-center gap-1">
              <div className="w-12 h-12 rounded-full bg-[#8eff71]/15 border border-[#8eff71]/30 flex items-center justify-center">
                <span className="font-headline font-bold text-sm text-[#8eff71]">{sym0.slice(0, 4)}</span>
              </div>
              <span className="text-[10px] tracking-wider text-white">{sym0}</span>
            </div>

            <div className="flex flex-col items-center text-center">
              <span className="font-headline font-bold text-base text-white tracking-wide">
                {sym0}/{sym1} POOL
              </span>
              <div className="flex gap-3 mt-1">
                <div className="flex flex-col items-end">
                  <span className="text-[9px] text-[#adaaaa]">TVL</span>
                  <span className="font-headline text-[#8eff71] text-sm font-bold">{fmtTvl(tvl)}</span>
                </div>
                <div className="w-px h-7 bg-[#494847]/30" />
                <div className="flex flex-col items-start">
                  <span className="text-[9px] text-[#adaaaa]">APY</span>
                  <span className="font-headline text-[#8eff71] text-sm font-bold">{fmtPct(apy, 1)}</span>
                </div>
              </div>
            </div>

            <div className="flex flex-col items-center gap-1">
              <div className="w-12 h-12 rounded-full bg-[#bf81ff]/15 border border-[#bf81ff]/30 flex items-center justify-center">
                <span className="font-headline font-bold text-sm text-[#bf81ff]">{sym1.slice(0, 4)}</span>
              </div>
              <span className="text-[10px] tracking-wider text-white">{sym1}</span>
            </div>
          </div>

          {/* Chart with highlighted range box */}
          <div className="h-40 w-full bg-[#131313] rounded-lg relative overflow-hidden border border-[#494847]/15">
            <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 100">
              <path
                d="M0,70 L10,50 L20,60 L30,40 L40,80 L50,30 L60,45 L70,20 L80,50 L90,10 L100,30"
                fill="none"
                stroke="#8eff71"
                strokeWidth="1.5"
                style={{ filter: 'drop-shadow(0 0 4px rgba(142,255,113,0.6))' }}
              />
            </svg>
            <div
              className="absolute top-1/2 -translate-y-1/2 h-3/4 border-2 border-[#8eff71] bg-[#8eff71]/10 rounded-lg flex items-center justify-center"
              style={{ left: `${(100 - widthPct) / 2}%`, width: `${widthPct}%` }}
            >
              <div className="text-center px-2">
                <span className="block font-headline font-bold text-[#8eff71] text-xs uppercase tracking-widest">
                  LIQUIDITY
                </span>
                <span className="block font-headline font-bold text-[#8eff71] text-xs uppercase tracking-widest">
                  RANGE
                </span>
              </div>
            </div>
          </div>

          {/* Hook copy — keeps the persona tone */}
          <p className="text-[#adaaaa] text-xs leading-snug">{card.hook}</p>

          {/* CTAs */}
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={onViewStrategy}
              className="py-3 rounded border border-[#8eff71]/40 bg-[#262626] text-[#8eff71] font-headline font-bold text-sm uppercase tracking-wider active:scale-95 transition-transform"
            >
              View Strategy
            </button>
            <button
              onClick={onConfigure}
              className="py-3 rounded bg-gradient-to-br from-[#8eff71] to-[#2ff801] text-[#0b5800] font-headline font-bold text-sm uppercase tracking-wider shadow-[0_0_12px_rgba(142,255,113,0.2)] active:scale-95 transition-transform"
            >
              Add Liquidity
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
