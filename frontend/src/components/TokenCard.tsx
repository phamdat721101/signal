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

// Yu-Gi-Oh style: confidence → stars (1-8)
function getStars(confidence?: number): number {
  const c = confidence ?? 50;
  if (c >= 90) return 8;
  if (c >= 80) return 7;
  if (c >= 70) return 6;
  if (c >= 60) return 5;
  if (c >= 50) return 4;
  if (c >= 40) return 3;
  if (c >= 30) return 2;
  return 1;
}

const verdictConfig: Record<string, { border: string; glow: string; icon: string; label: string }> = {
  APE: { border: 'from-[#8eff71] via-[#4ade80] to-[#22c55e]', glow: 'shadow-[0_0_20px_rgba(142,255,113,0.3)]', icon: '🔥', label: 'FIRE' },
  FADE: { border: 'from-[#ff7166] via-[#ef4444] to-[#dc2626]', glow: 'shadow-[0_0_20px_rgba(255,113,102,0.3)]', icon: '💀', label: 'DARK' },
  DYOR: { border: 'from-[#bf81ff] via-[#a855f7] to-[#7c3aed]', glow: 'shadow-[0_0_20px_rgba(191,129,255,0.3)]', icon: '🔮', label: 'SPELL' },
};

// SVG Candlestick Chart
function CandlestickChart({ ohlc, sparkline, price, verdict, cardType }: { ohlc?: number[][]; sparkline?: number[]; price: number; verdict: string; cardType?: string }) {
  const color = verdict === 'APE' ? '#8eff71' : verdict === 'FADE' ? '#ff7166' : '#bf81ff';

  // Use OHLC if available, otherwise enhanced sparkline
  if (ohlc && ohlc.length >= 4) {
    const w = 320, h = 120, pad = 10;
    const highs = ohlc.map(c => c[2]);
    const lows = ohlc.map(c => c[3]);
    const min = Math.min(...lows), max = Math.max(...highs);
    const range = max - min || 1;
    const barW = Math.max(4, (w - pad * 2) / ohlc.length - 2);

    const toY = (v: number) => pad + (1 - (v - min) / range) * (h - pad * 2);
    const entryY = toY(price);
    const targetY = toY(price * 1.015);
    const stopY = toY(price * 0.985);

    return (
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-32 rounded-lg">
        {/* Target/Stop zones */}
        <rect x={0} y={Math.min(targetY, entryY)} width={w} height={Math.abs(entryY - targetY)} fill="#8eff71" opacity="0.06" />
        <rect x={0} y={Math.min(entryY, stopY)} width={w} height={Math.abs(stopY - entryY)} fill="#ff7166" opacity="0.06" />
        {/* Entry line */}
        <line x1={0} y1={entryY} x2={w} y2={entryY} stroke="#666" strokeWidth="0.5" strokeDasharray="4 2" />
        <text x={w - 4} y={entryY - 3} fill="#888" fontSize="6" textAnchor="end">ENTRY</text>
        {/* Candles */}
        {ohlc.map((candle, i) => {
          const [, open, high, low, close] = candle;
          const x = pad + i * ((w - pad * 2) / ohlc.length);
          const bullish = close >= open;
          const bodyTop = toY(Math.max(open, close));
          const bodyBot = toY(Math.min(open, close));
          const bodyH = Math.max(1, bodyBot - bodyTop);
          const candleColor = bullish ? '#8eff71' : '#ff7166';
          return (
            <g key={i}>
              <line x1={x + barW / 2} y1={toY(high)} x2={x + barW / 2} y2={toY(low)} stroke={candleColor} strokeWidth="1" />
              <rect x={x} y={bodyTop} width={barW} height={bodyH} fill={bullish ? candleColor : 'none'} stroke={candleColor} strokeWidth="0.5" rx="0.5" />
            </g>
          );
        })}
      </svg>
    );
  }

  // Fallback: enhanced sparkline
  if (sparkline && sparkline.length > 2) {
    const w = 320, h = 120, pad = 10;
    const min = Math.min(...sparkline), max = Math.max(...sparkline), range = max - min || 1;
    const toY = (v: number) => pad + (1 - (v - min) / range) * (h - pad * 2);
    const points = sparkline.map((v, i) => `${pad + (i / (sparkline.length - 1)) * (w - pad * 2)},${toY(v)}`).join(' ');
    const entryY = toY(price);
    const gradId = `grad-${Math.random().toString(36).slice(2)}`;

    return (
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-32 rounded-lg">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon points={`${pad},${h - pad} ${points} ${w - pad},${h - pad}`} fill={`url(#${gradId})`} />
        <line x1={0} y1={entryY} x2={w} y2={entryY} stroke="#666" strokeWidth="0.5" strokeDasharray="4 2" />
        <polyline points={points} fill="none" stroke={color} strokeWidth="2" />
      </svg>
    );
  }

  const icons: Record<string, string> = { pool: '🌊', index: '📊', insight: '📰', trading: '📈' };
  return (
    <div className="w-full h-32 bg-[#0a0a0a] rounded-xl border border-[#262626] flex flex-col items-center justify-center gap-1">
      <span className="text-3xl">{icons[cardType || 'trading'] || '📈'}</span>
      <span className="text-[9px] text-[#494847] uppercase">{cardType || 'trading'}</span>
    </div>
  );
}

export default function TokenCard({ card, onApe, onFade }: { card: Card; onApe: () => void; onFade: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const verdict = card.verdict || 'DYOR';
  const vCfg = verdictConfig[verdict] || verdictConfig.DYOR;
  const stars = getStars(card.confidence ?? card.risk_score);
  const atk = card.confidence ?? Math.max(10, 100 - (card.risk_score ?? 50));
  const def = 100 - (card.risk_score ?? 50);
  const pctColor = card.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';

  return (
    <div className={`w-full max-w-sm mx-auto rounded-2xl overflow-hidden select-none ${vCfg.glow}`}>
      {/* Holographic gradient border */}
      <div className={`p-[2px] rounded-2xl bg-gradient-to-br ${vCfg.border}`}>
        <div className="bg-[#0e0e0e] rounded-2xl overflow-hidden">

          {/* === HEADER === */}
          <div className="flex items-center justify-between px-3 pt-3 pb-1">
            {/* Attribute icon */}
            <div className="flex items-center gap-2">
              <span className="text-xl">{vCfg.icon}</span>
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="font-bold text-white text-sm">${card.token_symbol}</span>
                  <span className="text-[9px] text-[#adaaaa]">{card.token_name}</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="font-bold text-white text-sm">{fmtPrice(card.price)}</span>
                  <span className={`text-[10px] ${pctColor}`}>{card.price_change_24h >= 0 ? '+' : ''}{card.price_change_24h.toFixed(1)}%</span>
                </div>
              </div>
            </div>
            {/* Level stars */}
            <div className="flex items-center gap-0.5">
              {Array.from({ length: stars }).map((_, i) => (
                <span key={i} className="text-[10px] text-yellow-400">★</span>
              ))}
            </div>
          </div>

          {/* === CARD ART: Candlestick Chart === */}
          <div className="px-2 cursor-pointer" onClick={() => setExpanded(!expanded)}>
            <div className="bg-[#0a0a0a] rounded-xl border border-[#262626] overflow-hidden">
              {card.image_url && card.card_type === 'insight' ? (
                <img src={card.image_url} alt="" className="w-full h-32 object-cover rounded-xl" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              ) : (
                <CandlestickChart ohlc={card.ohlc} sparkline={card.sparkline} price={card.price} verdict={verdict} cardType={card.card_type} />
              )}
              {/* Pattern badges overlaid */}
              {card.patterns && card.patterns.length > 0 && (
                <div className="flex gap-1 px-2 pb-1.5 -mt-1">
                  {card.patterns.slice(0, 3).map((p: any, i: number) => (
                    <span key={i} className={`text-[8px] px-1.5 py-0.5 rounded ${p.direction === 'bullish' ? 'bg-[#8eff71]/10 text-[#8eff71]' : p.direction === 'bearish' ? 'bg-[#ff7166]/10 text-[#ff7166]' : 'bg-[#bf81ff]/10 text-[#bf81ff]'}`}>
                      {p.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* === STATS BAR (ATK/DEF style) === */}
          <div className="flex items-center justify-between px-3 py-2">
            <div className="flex items-center gap-1">
              <span className="text-[9px] font-bold text-[#8eff71]">ATK</span>
              <span className="text-xs font-bold text-white">{atk}%</span>
            </div>
            <div className="text-[9px] text-[#494847] uppercase tracking-wider">{card.card_type === 'pool' ? '🌊 POOL' : verdict}</div>
            <div className="flex items-center gap-1">
              <span className="text-[9px] font-bold text-[#60a5fa]">DEF</span>
              <span className="text-xs font-bold text-white">{def}%</span>
            </div>
          </div>

          {/* === FLAVOR TEXT (hook) === */}
          <div className="px-3 pb-2">
            <p className="text-xs text-[#e0e0e0] italic leading-snug">{card.hook}</p>
          </div>

          {/* === EXPANDABLE ANALYSIS === */}
          <div className={`overflow-hidden transition-all duration-300 ${expanded ? 'max-h-[600px] opacity-100' : 'max-h-0 opacity-0'}`}>
            <div className="px-3 pb-3 space-y-2 border-t border-[#262626] pt-2">
              {/* Verdict reason */}
              {card.verdict_reason && (
                <div className="bg-[#1a1a1a] p-2 rounded-lg">
                  <div className="text-[8px] text-[#bf81ff] uppercase font-bold mb-0.5">Analysis</div>
                  <p className="text-[11px] text-[#ccc]">{card.verdict_reason}</p>
                  {card.roast && <p className="text-[10px] text-[#bf81ff]/70 italic mt-1">{card.roast}</p>}
                </div>
              )}

              {/* AI Prediction / Trade Plan */}
              {card.trade_plan && (
                <div className="bg-[#0e1a0e] border border-[#8eff71]/20 p-2 rounded-lg">
                  <div className="text-[8px] text-[#8eff71] uppercase font-bold mb-1">🎯 AI Prediction</div>
                  <div className="grid grid-cols-2 gap-1 text-[10px]">
                    {card.trade_plan.entry && <div><span className="text-[#888]">Entry:</span> <span className="text-white">{card.trade_plan.entry}</span></div>}
                    {card.trade_plan.target && <div><span className="text-[#888]">Target:</span> <span className="text-[#8eff71]">{card.trade_plan.target}</span></div>}
                    {card.trade_plan.stop && <div><span className="text-[#888]">Stop:</span> <span className="text-[#ff7166]">{card.trade_plan.stop}</span></div>}
                    {card.trade_plan.position_size && <div><span className="text-[#888]">Size:</span> <span className="text-white">{card.trade_plan.position_size}</span></div>}
                  </div>
                </div>
              )}

              {/* Why Now */}
              {card.why_now && (
                <div className="bg-[#1a1a2e] border border-[#bf81ff]/20 p-2 rounded-lg">
                  <div className="text-[8px] text-[#bf81ff] uppercase font-bold">⚡ Why Now</div>
                  <p className="text-[10px] text-[#ccc] mt-0.5">{card.why_now}</p>
                </div>
              )}

              {/* Agent Reports */}
              {card.agent_reports && (
                <div className="space-y-1">
                  <div className="text-[8px] text-[#adaaaa] uppercase font-bold">🤖 Agent Reports</div>
                  {card.agent_reports.technical && <p className="text-[9px] text-[#8eff71]/80 bg-[#0e1a0e] p-1.5 rounded">📊 {card.agent_reports.technical.slice(0, 120)}</p>}
                  {card.agent_reports.sentiment && <p className="text-[9px] text-[#bf81ff]/80 bg-[#1a1a2e] p-1.5 rounded">💬 {card.agent_reports.sentiment.slice(0, 120)}</p>}
                  {card.agent_reports.fundamentals && <p className="text-[9px] text-[#60a5fa]/80 bg-[#0e1a2e] p-1.5 rounded">📈 {card.agent_reports.fundamentals.slice(0, 120)}</p>}
                </div>
              )}

              {/* Debate summary */}
              {card.debate_summary && (
                <p className="text-[9px] text-[#888] italic">⚖️ {card.debate_summary}</p>
              )}

              {card.institutional_context && card.institutional_context.length > 0 && (
                <div className="bg-[#0e1a1a] border border-[#8eff71]/20 p-2 rounded-lg">
                  <div className="text-[8px] text-[#8eff71] uppercase font-bold mb-1">🏦 Smart Money Intel</div>
                  <div className="space-y-1">
                    {card.institutional_context.map((item: any, i: number) => (
                      <div key={i} className="flex items-center gap-1.5 text-[10px]">
                        <span>{item.emoji}</span>
                        <span className="text-[#888]">{item.label}:</span>
                        <span className="text-white">{item.value}</span>
                      </div>
                    ))}
                  </div>
                  <div className="px-3 pb-1">
                    <a href="https://sosovalue.com" target="_blank" rel="noopener noreferrer" className="text-[7px] text-[#494847] hover:text-[#bf81ff] transition-colors">Powered by SosoValue</a>
                  </div>
                </div>
              )}

              {card.research_summary?.summary && (
                <div className="bg-[#0e0e1a] border border-[#4a3aed]/20 p-2 rounded-lg">
                  <div className="text-[8px] text-[#bf81ff] uppercase font-bold mb-1">🔬 AI Research</div>
                  <p className="text-[10px] text-[#ccc]">{card.research_summary.summary.slice(0, 200)}</p>
                  {card.research_summary.key_findings?.length > 0 && (
                    <div className="mt-1 space-y-0.5">
                      {card.research_summary.key_findings.slice(0, 3).map((f: string, i: number) => (
                        <p key={i} className="text-[9px] text-[#888]">• {f}</p>
                      ))}
                    </div>
                  )}
                  <a href="https://sosovalue.com/research" target="_blank" rel="noopener noreferrer" className="text-[7px] text-[#494847] hover:text-[#bf81ff] mt-1 block">Full analysis on SosoValue →</a>
                </div>
              )}

              {/* Metrics row */}
              <div className="flex gap-1.5">
                <div className="flex-1 bg-[#1a1a1a] p-1.5 rounded text-center">
                  <div className="text-[7px] text-[#888] uppercase">MCap</div>
                  <div className="text-[10px] text-white font-bold">{fmt(card.market_cap)}</div>
                </div>
                <div className="flex-1 bg-[#1a1a1a] p-1.5 rounded text-center">
                  <div className="text-[7px] text-[#888] uppercase">Vol</div>
                  <div className="text-[10px] text-white font-bold">{fmt(card.volume_24h)}</div>
                </div>
                {card.position_guide && (
                  <div className="flex-1 bg-[#1a1a1a] p-1.5 rounded text-center">
                    <div className="text-[7px] text-[#888] uppercase">Size</div>
                    <div className="text-[9px] text-white">{card.position_guide.slice(0, 20)}</div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Expand hint */}
          <div className="text-center pb-1">
            <button onClick={() => setExpanded(!expanded)} className="text-[9px] text-[#494847] hover:text-[#adaaaa] transition-colors">
              {expanded ? '▲ collapse' : '▼ tap to analyze'}
            </button>
          </div>

          {/* === ACTION BUTTONS === */}
          <div className="flex gap-2 px-3 pb-3">
            <button onClick={onFade}
              className="flex-1 bg-[#1a1a1a] border border-[#ff7166]/40 text-[#ff7166] font-bold py-3 rounded-xl flex items-center justify-center gap-1.5 active:scale-95 transition-transform text-sm">
              💀 FADE
            </button>
            <button onClick={onApe}
              className="flex-1 bg-gradient-to-r from-[#8eff71] to-[#4ade80] text-[#0b5800] font-black py-3 rounded-xl flex items-center justify-center gap-1.5 active:scale-95 transition-transform text-sm shadow-[0_0_15px_rgba(142,255,113,0.2)]">
              🔥 APE
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
