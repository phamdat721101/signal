/**
 * TradingSignalCard — feed card for `card_type === 'trading_signal'`.
 *
 * Single Responsibility: render the signal + raise APE/FADE/EXECUTE
 * via callbacks. No transaction logic, no global state. Mirrors
 * LpBattleCard styling (Kinetic Terminal palette).
 *
 * The candle chart with entry/target/stop overlays is fetched lazily
 * from `/api/cards/{id}/klines` (5-min server cache, single-flight)
 * and rendered through a pure-SVG `EntryPatternChart` so the user can
 * SEE the price action that led to the AI verdict.
 */
import { useQuery } from '@tanstack/react-query';
import type { Card } from '../hooks/useCards';
import { config } from '../config';
import EntryPatternChart, { type Candle } from './EntryPatternChart';

// SoDex testnet perps — symbols actually listed (from /markets/symbols).
// Mirrors backend `sodex_client.SODEX_SYMBOL_IDS`. When a card's symbol
// isn't here we hide the EXECUTE button to preempt the 422 round-trip.
const SODEX_SUPPORTED = new Set(['BTC', 'ETH', 'SOL', 'AVAX', 'SUI', 'LINK']);

interface Props {
  card: Card;
  onApe: () => void;
  onFade: () => void;
  /** Called when the user taps the EXECUTE CTA inside the detail panel. */
  onExecute?: () => void;
  /** When true, EXECUTE button is disabled and shows a spinner state. */
  isExecuting?: boolean;
}

function fmtUsd(n?: number | null) {
  if (n == null || !isFinite(n)) return '—';
  if (n >= 1) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  return `$${n.toFixed(6)}`;
}

export default function TradingSignalCard({ card, onApe, onFade, onExecute, isExecuting }: Props) {
  const isLong = (card.verdict || 'APE').toUpperCase() === 'APE';
  const sigma = (card.volatility_7d_sigma ?? 0) * 100;
  const tp = card.trade_plan || {};
  const symbol = (card.token_symbol || '').toUpperCase();
  const isExecutable = SODEX_SUPPORTED.has(symbol);

  // Lazy candles fetch — 5-min cached server-side. Each unique symbol
  // hits CoinGecko at most once per 5 min regardless of viewer count.
  const { data: klines } = useQuery({
    queryKey: ['klines', card.id],
    queryFn: async () => {
      const r = await fetch(`${config.backendUrl}/api/cards/${card.id}/klines`);
      if (!r.ok) return { candles: [] as Candle[] };
      return r.json() as Promise<{ candles: Candle[]; trade_plan?: typeof tp }>;
    },
    staleTime: 5 * 60_000,
    retry: 0,
  });

  return (
    <div className="absolute inset-0 rounded-xl border-2 border-[#8eff71]/40 bg-[#0e0e0e] shadow-[0_0_24px_-8px_rgba(142,255,113,0.4)]">
      <div className="p-4 flex flex-col gap-3 h-full">
        {/* Header */}
        <div className="flex justify-between items-start">
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="text-2xl">⚡</span>
              <span className="font-headline font-bold text-lg text-white">{card.token_symbol}</span>
              <span
                className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                  isLong
                    ? 'bg-[#8eff71]/15 text-[#8eff71] border border-[#8eff71]/30'
                    : 'bg-[#ff7166]/15 text-[#ff7166] border border-[#ff7166]/30'
                }`}
              >
                {isLong ? 'LONG' : 'SHORT'}
              </span>
            </div>
            <span className="text-[11px] text-[#adaaaa] mt-0.5">{fmtUsd(card.price)} mark</span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[9px] text-[#adaaaa] uppercase">Confidence</span>
            <span className="font-headline font-bold text-[#8eff71] text-base">{card.confidence ?? 50}%</span>
          </div>
        </div>

        {/* Trade plan grid */}
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-[#131313] rounded p-2 border border-[#494847]/20">
            <div className="text-[9px] text-[#adaaaa] uppercase">Entry</div>
            <div className="font-headline font-bold text-white text-sm">{tp.entry || '—'}</div>
          </div>
          <div className="bg-[#0e1a0e] rounded p-2 border border-[#8eff71]/20">
            <div className="text-[9px] text-[#8eff71] uppercase">Target</div>
            <div className="font-headline font-bold text-[#8eff71] text-sm">{tp.target || '—'}</div>
          </div>
          <div className="bg-[#1a0e0e] rounded p-2 border border-[#ff7166]/20">
            <div className="text-[9px] text-[#ff7166] uppercase">Stop</div>
            <div className="font-headline font-bold text-[#ff7166] text-sm">{tp.stop || '—'}</div>
          </div>
        </div>

        {/* Entry-pattern chart — shows the price action behind the verdict.
            Lazy-loaded; tasteful empty state when the upstream is unavailable. */}
        <EntryPatternChart
          candles={klines?.candles ?? []}
          tradePlan={tp}
          verdict={card.verdict}
          height={120}
        />

        {/* Risk / venue chip row */}
        <div className="flex items-center gap-2 text-[10px]">
          <span className="bg-[#262626] text-[#adaaaa] px-2 py-1 rounded">σ7d {sigma.toFixed(2)}%</span>
          <span className="bg-[#262626] text-[#adaaaa] px-2 py-1 rounded">{tp.position_size || '$25 · 2x · IOC'}</span>
          <span className="bg-[#1a1a2e] text-[#bf81ff] px-2 py-1 rounded border border-[#bf81ff]/20">SoDex perps · testnet</span>
        </div>

        {/* Hook line */}
        <p className="text-[#adaaaa] text-xs leading-snug flex-1">{card.hook}</p>

        {/* Reasoning preview (one line; full text lives in tap-to-expand panel) */}
        {card.verdict_reason && (
          <p className="text-[10px] text-[#888] italic line-clamp-2">{card.verdict_reason}</p>
        )}

        {/* CTA row: FADE / APE for swipe parity, plus EXECUTE for explicit
            on-chain action. EXECUTE is the wedge — it converts a verdict
            into a real SoDex testnet order. */}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={onFade}
            className="py-3 rounded border border-[#ff7166]/40 bg-[#262626] text-[#ff7166] font-headline font-bold text-sm uppercase tracking-wider active:scale-95 transition-transform"
          >
            💨 Fade
          </button>
          <button
            onClick={onApe}
            className="py-3 rounded bg-gradient-to-br from-[#8eff71] to-[#2ff801] text-[#0b5800] font-headline font-bold text-sm uppercase tracking-wider shadow-[0_0_12px_rgba(142,255,113,0.2)] active:scale-95 transition-transform"
          >
            🦍 Ape
          </button>
        </div>
        {onExecute && (
          isExecutable ? (
            <button
              onClick={onExecute}
              disabled={isExecuting}
              className="py-2.5 rounded bg-[#1a1a2e] border border-[#bf81ff]/40 text-[#bf81ff] font-headline font-bold text-xs uppercase tracking-widest active:scale-95 transition-transform disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isExecuting ? '…executing…' : `⚡ Execute on SoDex (${tp.position_size || '$25 · 2x'})`}
            </button>
          ) : (
            <div className="py-2.5 rounded bg-[#262626] border border-[#494847]/30 text-[#adaaaa] font-label text-xs uppercase tracking-widest text-center">
              {symbol} not yet listed on SoDex testnet
            </div>
          )
        )}
      </div>
    </div>
  );
}
