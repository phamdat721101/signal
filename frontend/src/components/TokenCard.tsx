import { useState } from 'react';
import type { Card } from '../hooks/useCards';

function fmt(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(2)}`;
}

function fmtPrice(p: number): string {
  if (p >= 1) return `$${p.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (p >= 0.01) return `$${p.toFixed(4)}`;
  return `$${p.toFixed(6)}`;
}

function getCardEmoji(verdict: string, riskLevel?: string): string {
  const r = (riskLevel || '').toUpperCase();
  if (verdict === 'APE') {
    if (r === 'DEGEN' || r === 'HIGH') return '🦍🔥';
    if (r === 'MEDIUM' || r === 'MID') return '🚀';
    return '💎';
  }
  if (verdict === 'FADE') {
    if (r === 'DEGEN' || r === 'HIGH') return '💀';
    if (r === 'MEDIUM' || r === 'MID') return '😴';
    return '🐌';
  }
  return '🤔';
}

function riskColor(score: number): string {
  if (score <= 30) return '#8eff71';
  if (score <= 60) return '#f0c040';
  return '#ff7166';
}

const verdictStyle: Record<string, string> = {
  APE: 'bg-[#8eff71]/15 text-[#8eff71] border-[#8eff71]/30',
  FADE: 'bg-[#ff7166]/15 text-[#ff7166] border-[#ff7166]/30',
  DYOR: 'bg-[#bf81ff]/15 text-[#bf81ff] border-[#bf81ff]/30',
};

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1;
  const w = 280, h = 40;
  const points = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`).join(' ');
  const last = data[data.length - 1];
  const entryY = h - ((last - min) / range) * h;
  const targetY = h - ((last * 1.015 - min) / range) * h;
  const stopY = h - ((last * 0.985 - min) / range) * h;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-10">
      <rect x="0" y={Math.min(targetY, entryY)} width={w} height={Math.abs(entryY - targetY)} fill="#8eff71" opacity="0.08" />
      <rect x="0" y={Math.min(entryY, stopY)} width={w} height={Math.abs(stopY - entryY)} fill="#ff7166" opacity="0.08" />
      <line x1="0" y1={entryY} x2={w} y2={entryY} stroke="#494847" strokeWidth="0.5" strokeDasharray="4 2" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

const patternColor: Record<string, string> = {
  bullish: 'bg-[#8eff71]/10 text-[#8eff71] border-[#8eff71]/20',
  bearish: 'bg-[#ff7166]/10 text-[#ff7166] border-[#ff7166]/20',
  neutral: 'bg-[#bf81ff]/10 text-[#bf81ff] border-[#bf81ff]/20',
};

export default function TokenCard({ card, onApe, onFade }: { card: Card; onApe: () => void; onFade: () => void }) {
  const [imgError, setImgError] = useState(false);
  const verdict = card.verdict || 'DYOR';
  const pctColor = card.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
  const emoji = card.card_type === 'pool' ? '🌊💰' : getCardEmoji(verdict, card.risk_level);
  const score = card.risk_score ?? 50;

  return (
    <div className="w-full max-w-md mx-auto bg-[#131313] rounded-xl overflow-hidden flex flex-col border border-[#494847]/10 select-none">
      {/* Header: emoji + token + verdict + price */}
      <div className="flex items-center justify-between p-4 pb-2">
        <div className="flex items-center gap-3">
          <span className="text-4xl leading-none">{emoji}</span>
          <div className="w-9 h-9 rounded-full bg-[#262626] overflow-hidden flex-shrink-0">
            {card.image_url && !imgError ? (
              <img src={card.image_url} alt={card.token_symbol} className="w-full h-full object-cover" onError={() => setImgError(true)} />
            ) : (
              <div className="w-full h-full flex items-center justify-center font-headline font-bold text-xs text-[#adaaaa]">{card.token_symbol.slice(0, 2)}</div>
            )}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-headline font-bold text-lg text-white">${card.token_symbol}</span>
              <span className={`text-[9px] font-label font-bold px-2 py-0.5 rounded border ${verdictStyle[verdict] || verdictStyle.DYOR}`}>{verdict}</span>
              {(card as any).provider && <span className="text-[8px] bg-[#bf81ff]/10 text-[#bf81ff] px-1.5 py-0.5 rounded border border-[#bf81ff]/20">{(card as any).provider}</span>}
              {(card as any).execution_type === 'sodex' && <span className="text-[8px] bg-[#8eff71]/10 text-[#8eff71] px-1.5 py-0.5 rounded">LIVE 🟢</span>}
            </div>
            <div className="font-label text-[10px] text-[#adaaaa]">{card.token_name}</div>
          </div>
        </div>
        <div className="text-right">
          <div className="font-headline font-bold text-white">{fmtPrice(card.price)}</div>
          <div className={`font-label text-xs ${pctColor}`}>{card.price_change_24h >= 0 ? '+' : ''}{card.price_change_24h.toFixed(1)}%</div>
        </div>
      </div>

      {/* Hook as HERO — the main attraction */}
      <div className="px-4 pt-1 pb-1">
        <p className="text-base font-bold text-white leading-snug">{card.hook}</p>
        {card.roast && <p className="text-sm italic text-[#bf81ff]/80 mt-1">{card.roast}</p>}
      </div>

      {/* Sparkline + Patterns */}
      {card.sparkline && card.sparkline.length > 0 && (
        <div className="px-4 pb-1">
          <Sparkline data={card.sparkline} color={card.price_change_24h >= 0 ? '#8eff71' : '#ff7166'} />
          {card.patterns && card.patterns.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {card.patterns.slice(0, 2).map((p: any, i: number) => (
                <span key={i} className={`text-[9px] px-2 py-0.5 rounded border ${patternColor[p.direction] || patternColor.neutral}`}>
                  {p.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Risk meter */}
      <div className="px-4 pb-2">
        <div className="flex items-center gap-2">
          <span className="font-label text-[9px] text-[#494847] uppercase">Risk</span>
          <div className="flex-1 h-1.5 bg-[#262626] rounded-full overflow-hidden">
            <div className="h-full rounded-full transition-all" style={{ width: `${score}%`, backgroundColor: riskColor(score) }} />
          </div>
          <span className="font-label text-[9px] uppercase" style={{ color: riskColor(score) }}>{card.risk_level || 'MID'}</span>
        </div>
      </div>

      {/* Compact metrics row */}
      <div className="px-4 pb-2 flex gap-2">
        <div className="flex-1 bg-[#262626] px-3 py-2 rounded-lg">
          <div className="font-label text-[8px] text-[#adaaaa] uppercase">MCap</div>
          <div className="font-headline font-bold text-sm text-white">{fmt(card.market_cap)}</div>
        </div>
        <div className="flex-1 bg-[#262626] px-3 py-2 rounded-lg">
          <div className="font-label text-[8px] text-[#adaaaa] uppercase">Vol 24H</div>
          <div className="font-headline font-bold text-sm text-white">{fmt(card.volume_24h)}</div>
        </div>
        {card.metrics.length > 0 && (
          <div className="flex-1 bg-[#bf81ff]/10 px-3 py-2 rounded-lg border border-[#bf81ff]/20">
            <div className="font-label text-[8px] text-[#bf81ff] uppercase">AI</div>
            <div className="font-headline font-bold text-xs text-white truncate">
              {typeof card.metrics[0] === 'string' ? card.metrics[0] : `${card.metrics[0].emoji} ${card.metrics[0].value}`}
            </div>
          </div>
        )}
      </div>

      {/* Institutional context */}
      {card.institutional_context && card.institutional_context.length > 0 && (
        <div className="px-4 pb-2">
          <div className="mt-3 pt-3 border-t border-gray-800/50">
            <p className="text-[10px] text-[#bf81ff] uppercase tracking-wider mb-1.5 font-medium">📊 Smart Money Intel</p>
            {card.institutional_context.map((m, i) => (
              <div key={i} className="flex justify-between items-center text-xs py-0.5">
                <span className="text-gray-400">{m.emoji} {m.label}</span>
                <span className={m.sentiment === 'bullish' ? 'text-[#8eff71]' : m.sentiment === 'bearish' ? 'text-[#ff7166]' : 'text-white'}>{m.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Why verdict */}
      {card.verdict_reason && (
        <div className="px-4 pb-2">
          <div className="bg-[#262626] p-2 rounded-lg">
            <div className="font-label text-[9px] text-[#bf81ff] uppercase tracking-widest">Why {verdict}</div>
            <div className="text-[#adaaaa] text-xs mt-0.5">{card.verdict_reason}</div>
          </div>
        </div>
      )}

      {/* Trading Education */}
      {(card.trading_lesson || card.why_now || card.position_guide) && (
        <div className="px-4 pb-2 space-y-1.5">
          {card.why_now && (
            <div className="bg-[#1a1a2e] border border-[#bf81ff]/20 p-2 rounded-lg">
              <span className="font-label text-[8px] text-[#bf81ff] uppercase">⚡ Why Now</span>
              <p className="text-[#e0e0e0] text-[11px] mt-0.5">{card.why_now}</p>
            </div>
          )}
          {card.trading_lesson && (
            <div className="bg-[#0e1a0e] border border-[#8eff71]/20 p-2 rounded-lg">
              <span className="font-label text-[8px] text-[#8eff71] uppercase">💡 Lesson</span>
              <p className="text-[#e0e0e0] text-[11px] mt-0.5">{card.trading_lesson}</p>
            </div>
          )}
          <div className="flex gap-1.5">
            {card.position_guide && (
              <div className="flex-1 bg-[#262626] p-2 rounded-lg">
                <div className="font-label text-[8px] text-[#adaaaa] uppercase">📐 Size</div>
                <div className="text-[10px] text-white">{card.position_guide}</div>
              </div>
            )}
            {card.pattern_stats && (
              <div className="flex-1 bg-[#262626] p-2 rounded-lg">
                <div className="font-label text-[8px] text-[#adaaaa] uppercase">📊 History</div>
                <div className="text-[10px] text-[#8eff71]">{card.pattern_stats.win_rate}% win ({card.pattern_stats.samples} trades)</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3 px-4 pb-4">
        <button onClick={onFade}
          className="flex-1 bg-[#262626] border border-[#ff7166]/40 text-[#ff7166] font-headline font-bold py-3.5 rounded-lg flex items-center justify-center gap-2 active:scale-95 transition-transform">
          <span className="material-symbols-outlined">close</span>
          FADE
        </button>
        <button onClick={onApe}
          className="flex-1 ape-gradient text-[#0b5800] font-headline font-black py-3.5 rounded-lg flex items-center justify-center gap-2 glow-primary active:scale-95 transition-transform">
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>bolt</span>
          APE
        </button>
      </div>
    </div>
  );
}
