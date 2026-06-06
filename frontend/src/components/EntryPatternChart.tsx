/**
 * EntryPatternChart — pure-SVG candle chart with entry/target/stop overlays.
 *
 * Why pure SVG (no charting library):
 *   - Zero new dependency footprint (the project chose lightweight FE).
 *   - The chart is a small, fixed-shape visual (~14 candles, 3 horizontal
 *     lines, optional pattern markers). Any general-purpose chart library
 *     would dwarf the use case.
 *   - SVG renders crisply at any DPI and is trivially themeable with the
 *     project's neon palette.
 *
 * Single Responsibility: render `(candles, trade_plan)` → readable visual.
 *   No data fetching here — parent passes data via props (DIP).
 *
 * Empty / loading states: parent decides what to render when data is
 * missing; we just render the visual when given non-empty `candles`.
 */
import { useMemo } from 'react';

export interface Candle {
  /** [timestamp_ms, open, high, low, close] — CoinGecko shape. */
  0: number; 1: number; 2: number; 3: number; 4: number;
}

interface TradePlan {
  entry?: string;
  target?: string;
  stop?: string;
  position_size?: string;
}

interface Props {
  candles: Candle[];
  tradePlan?: TradePlan;
  /** APE = bullish (long); FADE = bearish (short). Flips green/red semantics. */
  verdict?: 'APE' | 'FADE' | string;
  /** Compact (default) for feed cards; tall for detail panels. */
  height?: number;
}

const G = '#8eff71';   // bullish (project green)
const R = '#ff7166';   // bearish (project red)
const W = '#ffffff';
const D = '#494847';   // dim grid

function parseUsd(s?: string): number | null {
  if (!s) return null;
  const n = parseFloat(s.replace(/[$,\s]/g, ''));
  return Number.isFinite(n) ? n : null;
}

export default function EntryPatternChart({
  candles, tradePlan, verdict = 'APE', height = 130,
}: Props) {
  const data = useMemo(() => {
    if (!candles || candles.length === 0) return null;
    const last = candles.slice(-14);              // last ~56h at 4h granularity
    const lows  = last.map(c => c[3]);
    const highs = last.map(c => c[2]);
    const entry  = parseUsd(tradePlan?.entry);
    const target = parseUsd(tradePlan?.target);
    const stop   = parseUsd(tradePlan?.stop);

    const yMin = Math.min(...lows,  ...[entry, target, stop].filter((v): v is number => v != null));
    const yMax = Math.max(...highs, ...[entry, target, stop].filter((v): v is number => v != null));
    const pad = (yMax - yMin) * 0.06 || (yMax * 0.01);
    return { last, yMin: yMin - pad, yMax: yMax + pad, entry, target, stop };
  }, [candles, tradePlan]);

  if (!data) {
    return (
      <div className="bg-[#0d0d0d] rounded-lg flex items-center justify-center"
           style={{ height }}>
        <span className="font-label text-[10px] text-[#494847] uppercase tracking-widest">
          Chart loading…
        </span>
      </div>
    );
  }

  const { last, yMin, yMax, entry, target, stop } = data;
  const W_VB = 280;                    // viewBox width (auto-scales via SVG)
  const H_VB = height;
  const padL = 4, padR = 44, padT = 8, padB = 8;
  const plotW = W_VB - padL - padR;
  const plotH = H_VB - padT - padB;
  const candleW = plotW / Math.max(last.length, 1);
  const yToPx = (v: number) => padT + plotH * (1 - (v - yMin) / Math.max(yMax - yMin, 1e-9));

  const isLong = (verdict || '').toUpperCase() !== 'FADE';
  const targetColor = isLong ? G : R;
  const stopColor   = isLong ? R : G;

  return (
    <svg viewBox={`0 0 ${W_VB} ${H_VB}`} className="w-full" preserveAspectRatio="none"
         role="img" aria-label="Entry pattern chart">
      {/* Background grid (top + bottom faint lines) */}
      <line x1={padL} x2={W_VB - padR} y1={padT} y2={padT} stroke={D} strokeWidth="0.5" strokeDasharray="2 3"/>
      <line x1={padL} x2={W_VB - padR} y1={H_VB - padB} y2={H_VB - padB} stroke={D} strokeWidth="0.5" strokeDasharray="2 3"/>

      {/* Candles */}
      {last.map((c, i) => {
        const o = c[1], h = c[2], l = c[3], cl = c[4];
        const x = padL + i * candleW + candleW / 2;
        const yO = yToPx(o), yC = yToPx(cl), yH = yToPx(h), yL = yToPx(l);
        const bullish = cl >= o;
        const color = bullish ? G : R;
        const bodyTop = Math.min(yO, yC);
        const bodyH = Math.max(Math.abs(yO - yC), 1);
        const bodyW = Math.max(candleW * 0.6, 2);
        return (
          <g key={i}>
            {/* wick */}
            <line x1={x} x2={x} y1={yH} y2={yL} stroke={color} strokeWidth="1"/>
            {/* body */}
            <rect x={x - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH}
                  fill={color} opacity={bullish ? 0.95 : 0.85}/>
          </g>
        );
      })}

      {/* Entry / Target / Stop horizontal annotations */}
      {entry != null && entry >= yMin && entry <= yMax && (
        <>
          <line x1={padL} x2={W_VB - padR} y1={yToPx(entry)} y2={yToPx(entry)}
                stroke={W} strokeWidth="1" strokeDasharray="3 3"/>
          <text x={W_VB - padR + 3} y={yToPx(entry) + 3}
                fill={W} fontFamily="ui-monospace,monospace" fontSize="9">
            entry · {tradePlan?.entry}
          </text>
        </>
      )}
      {target != null && target >= yMin && target <= yMax && (
        <>
          <line x1={padL} x2={W_VB - padR} y1={yToPx(target)} y2={yToPx(target)}
                stroke={targetColor} strokeWidth="1"/>
          <text x={W_VB - padR + 3} y={yToPx(target) + 3}
                fill={targetColor} fontFamily="ui-monospace,monospace" fontSize="9">
            target · {tradePlan?.target}
          </text>
        </>
      )}
      {stop != null && stop >= yMin && stop <= yMax && (
        <>
          <line x1={padL} x2={W_VB - padR} y1={yToPx(stop)} y2={yToPx(stop)}
                stroke={stopColor} strokeWidth="1"/>
          <text x={W_VB - padR + 3} y={yToPx(stop) + 3}
                fill={stopColor} fontFamily="ui-monospace,monospace" fontSize="9">
            stop · {tradePlan?.stop}
          </text>
        </>
      )}
    </svg>
  );
}
