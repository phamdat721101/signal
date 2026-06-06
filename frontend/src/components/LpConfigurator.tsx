/**
 * LpConfigurator — full-screen sheet for opening an LP position.
 *
 * Visual spec: lp-ui/lp_position_configurator/code.html. Layout:
 *   ┌──────────────────────────────────────────┐
 *   │  ← back     LP CONFIGURATOR     ⚙        │
 *   ├──────────────────────────────────────────┤
 *   │  Token A ($SYM0) — input + balance       │
 *   │  Token B ($SYM1) — auto-fill readonly    │
 *   │  Range chart + min/max sliders           │
 *   │  Stats: current price · pool share · fees│
 *   │  [ ZAP INTO POOL ]  or  [ OPEN ON UNIv3 ]│
 *   └──────────────────────────────────────────┘
 *
 * Single Responsibility: collect inputs → call /api/cards/{id}/lp-recipe →
 * dispatch ZAP via useSummonTransaction (when supported) or open dex_link.
 */
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Card } from '../hooks/useCards';
import { useLpQuote } from '../hooks/useLpQuote';
import { useLpRange, type LpPreset } from '../hooks/useLpRange';
import { useERC20Balance } from '../hooks/useERC20Balance';
import { useSummonTransaction } from '../hooks/useSummonTransaction';

const PRESETS: { id: LpPreset; label: string; sublabel: string }[] = [
  { id: 'conservative', label: 'Conservative', sublabel: 'k=2σ · widest' },
  { id: 'balanced',     label: 'Balanced',     sublabel: 'k=1σ · default' },
  { id: 'aggressive',   label: 'Aggressive',   sublabel: 'k=0.5σ · max fees' },
];

interface Props {
  card: Card;
  onClose: () => void;
}

function fmtUsd(n: number | null | undefined, digits = 2): string {
  if (n == null || !isFinite(n)) return '—';
  return `$${n.toFixed(digits)}`;
}

function fmtNum(n: number | null | undefined, digits = 4): string {
  if (n == null || !isFinite(n)) return '—';
  return n.toFixed(digits);
}

export default function LpConfigurator({ card, onClose }: Props) {
  const [preset, setPreset] = useState<LpPreset>('balanced');
  const [amountAStr, setAmountAStr] = useState('');
  const amountA = Number(amountAStr) || 0;

  const sym0 = card.token0_symbol || 'A';
  const sym1 = card.token1_symbol || 'B';

  // Local preview range (instant, no fetch); replaced by quote.min/max once
  // the user starts typing an amount.
  const sigma = card.volatility_7d_sigma ?? null;
  const localPreview = useLpRange(1.0, sigma, preset); // mid=1 for visual ratio

  // Live recipe (gated on amountA > 0).
  const { data: recipe, isFetching, error } = useLpQuote(card.id, amountA, preset);

  // Wallet balance for token A (chain-aware).
  const balance = useERC20Balance(card.token0_address, card.chain_id, card.token0_decimals ?? 18);

  // Summon path (Kinetic v4 hook). Disabled by recipe.supported.
  const { summon, isLoading: zapping, error: zapError } = useSummonTransaction();
  const [submitState, setSubmitState] = useState<'idle' | 'pending' | 'done'>('idle');

  const supported = recipe?.supported ?? false;
  const dexLink = recipe?.dex_link || card.dex_link || '';
  const ctaLabel = supported ? 'ZAP INTO POOL' : 'OPEN ON DEX';

  // Range readouts: prefer recipe (precise), fall back to local preview.
  const minPrice = recipe?.min_price ?? null;
  const maxPrice = recipe?.max_price ?? null;
  const rangeWidthPct = useMemo(() => {
    if (recipe?.min_price && recipe?.max_price) {
      const span = recipe.max_price - recipe.min_price;
      const mid = (recipe.max_price + recipe.min_price) / 2;
      if (mid > 0) return Math.max(15, Math.min(80, (span / mid) * 100));
    }
    const span = (localPreview.max - localPreview.min);
    return Math.max(15, Math.min(80, span * 100));
  }, [recipe, localPreview]);

  // Esc closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const onSubmit = async () => {
    if (!supported) {
      if (dexLink) window.open(dexLink, '_blank', 'noopener,noreferrer');
      return;
    }
    setSubmitState('pending');
    const r = await summon(card);
    setSubmitState(r ? 'done' : 'idle');
  };

  const submitDisabled = amountA <= 0 || zapping || isFetching || submitState === 'pending';

  return createPortal(
    <div className="fixed inset-0 z-[80] bg-[#0e0e0e] flex flex-col" role="dialog" aria-modal="true">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-white/5">
        <button onClick={onClose} className="text-[#adaaaa] hover:text-[#8eff71] active:scale-95 transition-transform" aria-label="close">
          <span className="text-xl">←</span>
        </button>
        <h1 className="font-headline font-bold tracking-tighter text-base text-[#8eff71] uppercase">
          LP Configurator
        </h1>
        <div className="w-6" />
      </header>

      {/* Body — single scroll container, fixed-size slots (CLS-free) */}
      <main className="flex-1 overflow-y-auto px-4 py-4 max-w-md mx-auto w-full space-y-4">
        {/* Token A input */}
        <section className="bg-[#131313] rounded-xl p-4">
          <div className="flex justify-between items-baseline mb-2">
            <label className="text-xs font-bold tracking-wider text-white uppercase">
              Token A — {sym0}
            </label>
            <span className="text-[10px] text-[#adaaaa]">
              Balance: {balance.isLoading ? '…' : Number(balance.formatted).toFixed(4)} {sym0}
            </span>
          </div>
          <input
            type="text"
            inputMode="decimal"
            value={amountAStr}
            onChange={(e) => setAmountAStr(e.target.value.replace(/[^0-9.]/g, ''))}
            placeholder="0.0"
            className="w-full bg-[#262626] border-none rounded-lg text-[#8eff71] font-headline text-xl px-4 py-3 caret-[#8eff71] focus:ring-1 focus:ring-[#8eff71]/40 outline-none"
            aria-label={`amount of ${sym0}`}
          />
        </section>

        {/* Token B readout */}
        <section className="bg-[#131313] rounded-xl p-4">
          <div className="flex justify-between items-baseline mb-2">
            <label className="text-xs font-bold tracking-wider text-white uppercase">
              Token B — {sym1}
            </label>
            <span className="text-[10px] text-[#adaaaa]">auto-derived</span>
          </div>
          <div className="w-full bg-[#262626] rounded-lg text-[#bf81ff] font-headline text-xl px-4 py-3">
            {amountA > 0 ? fmtNum(recipe?.token_b_amount, 6) : '—'}
          </div>
        </section>

        {/* Preset chips */}
        <section className="bg-[#131313] rounded-xl p-4">
          <div className="text-xs font-bold tracking-wider text-white uppercase mb-2">Range Preset</div>
          <div className="grid grid-cols-3 gap-2">
            {PRESETS.map((p) => {
              const active = p.id === preset;
              return (
                <button
                  key={p.id}
                  onClick={() => setPreset(p.id)}
                  className={`rounded-lg p-2 text-left transition-colors active:scale-95 ${
                    active ? 'bg-[#8eff71]/15 border border-[#8eff71]/40 text-[#8eff71]' : 'bg-[#262626] border border-transparent text-white'
                  }`}
                >
                  <div className="font-bold text-xs uppercase">{p.label}</div>
                  <div className="text-[9px] text-[#adaaaa]">{p.sublabel}</div>
                </button>
              );
            })}
          </div>
          {!sigma && (
            <p className="mt-2 text-[10px] text-[#adaaaa]">
              No 7d signal yet — using safe fixed bands.
            </p>
          )}
        </section>

        {/* Range chart placeholder w/ min/max readout */}
        <section className="bg-[#131313] rounded-xl p-4">
          <div className="h-32 w-full rounded-lg bg-[#262626] relative overflow-hidden border border-[#494847]/15">
            <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 100">
              <path
                d="M0,80 Q20,60 40,70 T80,30 T100,10"
                fill="none"
                stroke="#8eff71"
                strokeWidth="1.5"
                style={{ filter: 'drop-shadow(0 0 4px rgba(142,255,113,0.5))' }}
              />
            </svg>
            <div
              className="absolute top-0 bottom-0 border-2 border-[#8eff71] bg-[#8eff71]/10"
              style={{ left: `${(100 - rangeWidthPct) / 2}%`, width: `${rangeWidthPct}%` }}
            />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="flex justify-between bg-[#262626] rounded-lg px-3 py-2">
              <span className="text-[#adaaaa]">Min</span>
              <span className="text-[#8eff71] font-headline font-bold">{fmtNum(minPrice, 6)}</span>
            </div>
            <div className="flex justify-between bg-[#262626] rounded-lg px-3 py-2">
              <span className="text-[#adaaaa]">Max</span>
              <span className="text-[#8eff71] font-headline font-bold">{fmtNum(maxPrice, 6)}</span>
            </div>
          </div>
        </section>

        {/* Stats */}
        <section className="bg-[#131313] rounded-xl p-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-[#adaaaa]">Pool Share</span>
            <span className="font-headline font-bold text-[#8eff71]">
              {recipe ? `${recipe.pool_share_pct.toFixed(4)}%` : '—'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-[#adaaaa]">Estimated Fees (24h)</span>
            <span className="font-headline font-bold text-[#bf81ff]">
              {recipe ? fmtUsd(recipe.est_fee_24h_usd, 4) : '—'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-[#adaaaa]">Volatility (σ_7d)</span>
            <span className="font-headline text-white">
              {recipe?.sigma_7d != null ? `${(recipe.sigma_7d * 100).toFixed(2)}%` : '—'}
            </span>
          </div>
        </section>

        {(error || zapError) && (
          <div className="bg-[#ff7166]/10 border border-[#ff7166]/30 rounded-xl p-3 text-[#ff7166] text-xs">
            {String((zapError as any)?.message || error?.message || 'Something went wrong')}
          </div>
        )}
      </main>

      {/* Sticky CTA */}
      <footer className="border-t border-white/5 bg-[#131313] px-4 py-3">
        <div className="max-w-md mx-auto">
          <button
            onClick={onSubmit}
            disabled={submitDisabled}
            className="w-full bg-gradient-to-br from-[#8eff71] to-[#2ff801] text-[#0b5800] font-headline font-bold text-base py-4 rounded-lg shadow-[inset_0_1px_0_rgba(255,255,255,0.2)] active:scale-95 transition-all uppercase tracking-widest disabled:opacity-40"
          >
            {submitState === 'pending' ? 'CONFIRM IN WALLET…' : submitState === 'done' ? 'SUMMONED ✓' : ctaLabel}
          </button>
          {!supported && dexLink && amountA > 0 && (
            <p className="mt-2 text-[10px] text-[#adaaaa] text-center">
              Pair not on Kinetic v4 hook — opens external DEX in a new tab.
            </p>
          )}
        </div>
      </footer>
    </div>,
    document.body
  );
}
