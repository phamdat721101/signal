/**
 * LpBattleCard — read-only feed card for `card_type === 'pool'`.
 *
 * Shows the AI-recommended range (auto-picked from the 3 σ-derived
 * presets — the one with the highest projected 24-h fee yield) and
 * a single "OPEN ON DEX" CTA that deep-links to `card.dex_link`.
 *
 * Single Responsibility: render the read-only summary + raise an
 * "open" intent via callback. No transaction logic, no in-app
 * liquidity flow — depositing happens on the host DEX (Uniswap,
 * Aerodrome, Curve, etc.) per `card.dex_link`.
 */
import { useQuery } from '@tanstack/react-query';
import type { Card } from '../hooks/useCards';
import { config } from '../config';

interface Props {
  card: Card;
  /** Tap "OPEN ON DEX" — opens `card.dex_link` in a new tab. */
  onOpenDex: () => void;
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

export default function LpBattleCard({ card, onOpenDex }: Props) {
  const apy = card.price ?? 0;            // pool cards reuse `price` for APY
  const tvl = card.market_cap ?? 0;       // and `market_cap` for TVL
  const sym0 = card.token0_symbol || (card.token_symbol || '').split(/[-/]/)[0] || 'A';
  const sym1 = card.token1_symbol || (card.token_symbol || '').split(/[-/]/)[1] || 'B';

  // Lazy-fetch the AI-recommended range. Backend picks the preset with
  // the highest projected 24-h fee yield; we just render the winner.
  const { data: recipe } = useQuery({
    queryKey: ['lp-recipe', card.id, 'auto'],
    queryFn: async () => {
      const r = await fetch(`${config.backendUrl}/api/cards/${card.id}/lp-recipe?preset=auto&amount_a=100`);
      if (!r.ok) return null;
      return r.json() as Promise<{
        recommended?: string;
        preset?: string;
        min_price?: number | null;
        max_price?: number | null;
        est_fee_24h_usd?: number;
        dex_link?: string;
      }>;
    },
    staleTime: 5 * 60_000,
    retry: 0,
  });

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

          {/* AI-recommended range — most profitable preset (highest projected 24h fees). */}
          <div className="bg-[#131313] rounded-lg p-3 border border-[#8eff71]/20">
            <div className="flex items-center justify-between mb-1">
              <span className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest">
                AI-Recommended Range
              </span>
              {recipe?.recommended ? (
                <span className="text-[9px] font-label font-bold px-1.5 py-0.5 rounded bg-[#8eff71]/15 text-[#8eff71] uppercase tracking-widest">
                  {recipe.recommended}
                </span>
              ) : null}
            </div>
            <div className="flex items-center justify-between">
              <span className="font-headline text-sm font-bold text-white font-mono">
                {recipe?.min_price != null && recipe?.max_price != null
                  ? `${recipe.min_price.toFixed(4)} → ${recipe.max_price.toFixed(4)}`
                  : '—'}
              </span>
              <span className="font-headline text-sm font-bold text-[#8eff71]">
                {recipe?.est_fee_24h_usd != null
                  ? `$${recipe.est_fee_24h_usd.toFixed(2)}/day`
                  : '—'}
              </span>
            </div>
          </div>

          {/* Hook copy — keeps the persona tone */}
          <p className="text-[#adaaaa] text-xs leading-snug">{card.hook}</p>

          {/* Single CTA: open the host DEX where the user actually deposits. */}
          <button
            onClick={onOpenDex}
            className="py-3 rounded bg-gradient-to-br from-[#8eff71] to-[#2ff801] text-[#0b5800] font-headline font-bold text-sm uppercase tracking-wider shadow-[0_0_12px_rgba(142,255,113,0.2)] active:scale-95 transition-transform"
          >
            🌊 Open on DEX
          </button>
        </div>
      </div>
    </div>
  );
}
