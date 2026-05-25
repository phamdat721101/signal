import { useState } from 'react';
import type { Card } from '../hooks/useCards';
import { shareToX, config, isCardTradeable } from '../config';
import NetworkBadge from './NetworkBadge';

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
function getStars(card: { rarity?: string; confidence?: number }): number {
  if (card.rarity === 'legendary') return 8;
  if (card.rarity === 'epic') return 7;
  if (card.rarity === 'rare') return 6;
  if (card.rarity === 'uncommon') return 4;
  if (card.rarity === 'common') return 2;
  // fallback to existing confidence-based logic
  const c = card.confidence ?? 50;
  if (c >= 90) return 8;
  if (c >= 80) return 7;
  if (c >= 70) return 6;
  if (c >= 60) return 5;
  if (c >= 50) return 4;
  if (c >= 40) return 3;
  if (c >= 30) return 2;
  return 1;
}

function getRarityBadge(rarity?: string): string {
  if (rarity === 'legendary') return '💎';
  if (rarity === 'epic') return '🔮';
  if (rarity === 'rare') return '✨';
  return '';
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
  const stars = getStars(card);
  const rarityBadge = getRarityBadge(card.rarity);
  const atk = card.confidence ?? Math.max(10, 100 - (card.risk_score ?? 50));
  const def = 100 - (card.risk_score ?? 50);
  const pctColor = card.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
  const glowClass = card.rarity === 'legendary'
    ? vCfg.glow.replace('0.3)', '0.6)')
    : vCfg.glow;

  return (
    <div className={`w-full max-w-sm mx-auto rounded-2xl overflow-hidden select-none ${glowClass}`}>
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
              <NetworkBadge chainId={(card as any).chain_id ?? config.xlayer.testnetId} />
              {isCardTradeable(card) && <span className="text-[9px] bg-[#bf81ff]/15 text-[#bf81ff] font-bold px-1.5 py-0.5 rounded">🔮 LP</span>}
              {card.card_type === 'gem' && <span className="text-[9px] bg-[#ffd700]/15 text-[#ffd700] font-bold px-1.5 py-0.5 rounded">💎 GEM</span>}
              {rarityBadge && <span className="text-sm mr-0.5 ml-1">{rarityBadge}</span>}
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
            {card.sentiment_score && card.sentiment_score !== 0 ? (
              <div className="flex items-center gap-1">
                <span className="text-[9px]">{card.sentiment_score > 20 ? '📈' : card.sentiment_score < -20 ? '📉' : '➡️'}</span>
                <span className={`text-[10px] font-bold ${card.sentiment_score > 20 ? 'text-[#8eff71]' : card.sentiment_score < -20 ? 'text-[#ff7166]' : 'text-[#adaaaa]'}`}>
                  {card.sentiment_score > 0 && '+'}{card.sentiment_score}
                </span>
              </div>
            ) : (
              <div className="text-[9px] text-[#494847] uppercase tracking-wider">{card.card_type === 'pool' ? '🌊 POOL' : verdict}</div>
            )}
            <div className="flex items-center gap-1">
              <span className="text-[9px] font-bold text-[#60a5fa]">DEF</span>
              <span className="text-xs font-bold text-white">{def}%</span>
            </div>
          </div>

          {/* === FLAVOR TEXT (hook) === */}
          <div className="px-3 pb-2">
            <p className="text-xs text-[#e0e0e0] italic leading-snug">{card.hook}</p>
          </div>

          {/* === SOSOVALUE DATA HIGHLIGHT (always visible) === */}
          {card.institutional_context && card.institutional_context.length > 0 && (
            <div className="px-3 pb-2">
              <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-[#0e0e1a]/80 border border-[#6366f1]/20">
                <span className="text-[10px]">{card.institutional_context[0].emoji}</span>
                <span className="text-[9px] text-[#a5b4fc] font-medium truncate flex-1">
                  {card.institutional_context[0].label}: {card.institutional_context[0].value}
                </span>
                <span className="text-[7px] text-[#6366f1] font-bold px-1 py-0.5 rounded bg-[#6366f1]/10">SoSoValue</span>
              </div>
            </div>
          )}

          {/* === EXPANDABLE ANALYSIS (bottom-sheet overlay — no CLS) === */}
          {expanded && (
            <div className="fixed inset-0 z-50 bg-black/70 flex items-end" onClick={() => setExpanded(false)}>
              <div className="w-full max-w-md mx-auto bg-[#0e0e0e] rounded-t-2xl p-4 max-h-[80vh] overflow-y-auto animate-[slideUp_0.25s_ease-out]" onClick={e => e.stopPropagation()}>
                <div className="w-10 h-1 bg-[#494847] rounded-full mx-auto mb-3" />
                <div className="space-y-2">
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
                <div className="bg-[#0e0e1a] border border-[#6366f1]/30 p-2 rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-[8px] text-[#8eff71] uppercase font-bold">🏦 Smart Money Intel</div>
                    <a href="https://sosovalue.com" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[#6366f1]/15 hover:bg-[#6366f1]/25 transition-colors">
                      <span className="text-[7px] font-bold text-[#a5b4fc]">SoSoValue</span>
                    </a>
                  </div>
                  <div className="space-y-1">
                    {card.institutional_context.map((item: any, i: number) => (
                      <div key={i} className="flex items-center gap-1.5 text-[10px]">
                        <span>{item.emoji}</span>
                        <span className="text-[#888]">{item.label}:</span>
                        <span className="text-white">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {card.research_summary?.summary && (
                <div className="bg-[#0e0e1a] border border-[#6366f1]/20 p-2 rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-[8px] text-[#bf81ff] uppercase font-bold">🔬 AI Research</div>
                    <a href="https://sosovalue.com/research" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[#6366f1]/10 hover:bg-[#6366f1]/20 transition-colors">
                      <span className="text-[7px] font-bold text-[#a5b4fc]">SoSoValue →</span>
                    </a>
                  </div>
                  <p className="text-[10px] text-[#ccc]">{card.research_summary.summary.slice(0, 200)}</p>
                  {card.research_summary.key_findings?.length > 0 && (
                    <div className="mt-1 space-y-0.5">
                      {card.research_summary.key_findings.slice(0, 3).map((f: string, i: number) => (
                        <p key={i} className="text-[9px] text-[#888]">• {f}</p>
                      ))}
                    </div>
                  )}
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
                <button className="w-full mt-3 bg-[#262626] text-[#adaaaa] py-2 rounded-lg text-sm" onClick={() => setExpanded(false)}>Close</button>
              </div>
            </div>
          )}

          {/* Analyze trigger */}
          <div className="text-center pb-1">
            <button onClick={() => setExpanded(true)} className="text-[9px] text-[#494847] hover:text-[#adaaaa] transition-colors">
              ▼ tap to analyze
            </button>
          </div>

          {/* Source badge */}
          {card.source === "sosovalue" && (
            <div className="flex justify-center pb-1">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#6366f1]/10 border border-[#6366f1]/20">
                <span className="text-[8px] text-[#a5b4fc] font-medium">Data by SoSoValue</span>
              </span>
            </div>
          )}

          {/* === ACTION BUTTONS === */}
          <div className="flex gap-2 px-3 pb-2">
            <button onClick={onFade}
              className="flex-1 bg-[#1a1a1a] border border-[#ff7166]/40 text-[#ff7166] font-bold py-3 rounded-xl flex items-center justify-center gap-1.5 active:scale-95 transition-transform text-sm">
              💀 FADE
            </button>
            <button onClick={onApe}
              className="flex-1 bg-gradient-to-r from-[#8eff71] to-[#4ade80] text-[#0b5800] font-black py-3 rounded-xl flex items-center justify-center gap-1.5 active:scale-95 transition-transform text-sm shadow-[0_0_15px_rgba(142,255,113,0.2)]">
              🔥 APE
            </button>
          </div>
          {/* Share to X */}
          <div className="px-3 pb-3">
            <button onClick={() => shareToX(
              `${verdict === 'APE' ? '🔥' : '💀'} ${verdict} on $${card.token_symbol} (${atk}% confidence)\n\n"${card.hook}"\n\n#ApeOrFade @KineticApp`
            )} className="w-full bg-[#1a1a1a] border border-[#494847]/30 text-[#adaaaa] text-xs font-medium py-2 rounded-xl flex items-center justify-center gap-1.5 active:scale-95 transition-transform hover:border-[#6366f1]/40 hover:text-white">
              𝕏 Share Card
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


/* ─── Shared sub-components for new card types ─── */

function WhyNowBox({ text, accent = 'purple' }: { text: string; accent?: 'purple' | 'amber' }) {
  const border = accent === 'amber' ? 'border-[#f59e0b]/20' : 'border-[#bf81ff]/20';
  const bg = accent === 'amber' ? 'bg-[#f59e0b]/10' : 'bg-[#bf81ff]/10';
  const label = accent === 'amber' ? 'text-[#f59e0b]' : 'text-[#bf81ff]';
  return (
    <div className={`${bg} ${border} border p-3 rounded-xl`}>
      <div className={`text-[9px] font-bold ${label} uppercase tracking-widest mb-1`}>⚡ WHY NOW</div>
      <p className="text-[11px] text-[#adaaaa] leading-relaxed">{text}</p>
    </div>
  );
}

function VerdictPill({ verdict }: { verdict: string }) {
  const isApe = verdict === 'APE';
  const color = isApe ? 'text-[#8eff71] bg-[#8eff71]/10 border-[#8eff71]/20' : 'text-[#ff7166] bg-[#ff7166]/10 border-[#ff7166]/20';
  return (
    <div className={`${color} border rounded-full py-1.5 flex items-center justify-center gap-1.5`}>
      <span className="text-xs">✨</span>
      <span className="font-bold text-[10px] uppercase tracking-widest">Verdict: {verdict}</span>
    </div>
  );
}

function ActionButtons({ onApe, onFade }: { onApe: () => void; onFade: () => void }) {
  return (
    <div className="grid grid-cols-2 h-14 border-t border-white/5">
      <button onClick={onFade} className="flex items-center justify-center gap-1.5 hover:bg-[#ff7166]/10 active:scale-95 transition-all">
        <span className="text-[#ff7166] font-black text-lg">↘ FADE</span>
      </button>
      <button onClick={onApe} className="flex items-center justify-center gap-1.5 bg-[#8eff71] hover:bg-[#2ff801] active:scale-95 transition-all">
        <span className="text-[#0b5800] font-black text-lg">↗ APE</span>
      </button>
    </div>
  );
}

/* ─── IndexBattleCard ─── */

export function IndexBattleCard({ card, onApe, onFade }: { card: Card; onApe: () => void; onFade: () => void }) {
  const ctx = card.institutional_context || [];
  const left = ctx[0] || { label: '?', value: '0%' };
  const right = ctx[1] || { label: '?', value: '0%' };
  const leftPct = parseFloat(left.value) || 0;
  const rightPct = parseFloat(right.value) || 0;
  const total = Math.abs(leftPct) + Math.abs(rightPct) || 1;
  const leftMomentum = Math.round((Math.abs(leftPct) / total) * 100);

  return (
    <div className="w-full max-w-sm mx-auto rounded-lg overflow-hidden select-none kinetic-glow border border-[#bf81ff]/30 bg-[#131313]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[#bf81ff]/10 border-b border-[#bf81ff]/20">
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-[#bf81ff] rounded-sm">
          <span className="text-[10px] font-black text-white tracking-widest">⚔️ INDEX BATTLE</span>
        </div>
        <div className="flex gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-[#8eff71] ape-pulse" />
          <div className="w-1.5 h-1.5 rounded-full bg-[#bf81ff]/50" />
        </div>
      </div>
      {/* VS Comparison */}
      <div className="relative grid grid-cols-2 gap-px bg-[#262626]/30">
        <div className="bg-[#1a1919] p-5 flex flex-col items-center text-center">
          <div className="text-[9px] font-bold text-[#adaaaa] tracking-tight mb-1">AGGREGATED INDEX</div>
          <div className="font-bold text-3xl text-white mb-1">{left.label}</div>
          <div className={`font-bold text-lg ${leftPct >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>{left.value}</div>
          <div className="w-full mt-4 bg-[#262626] h-2 rounded-full overflow-hidden">
            <div className="bg-[#8eff71] h-full rounded-full" style={{ width: `${leftMomentum}%` }} />
          </div>
          <div className="mt-1 text-[9px] text-[#adaaaa] uppercase tracking-widest">{leftMomentum}% MOMENTUM</div>
        </div>
        <div className="bg-[#1a1919] p-5 flex flex-col items-center text-center">
          <div className="text-[9px] font-bold text-[#adaaaa] tracking-tight mb-1">RISK-ON INDEX</div>
          <div className="font-bold text-3xl text-white mb-1">{right.label}</div>
          <div className={`font-bold text-lg ${rightPct >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>{right.value}</div>
          <div className="w-full mt-4 bg-[#262626] h-2 rounded-full overflow-hidden">
            <div className="bg-[#ff7166] h-full rounded-full" style={{ width: `${100 - leftMomentum}%` }} />
          </div>
          <div className="mt-1 text-[9px] text-[#adaaaa] uppercase tracking-widest">{100 - leftMomentum}% MOMENTUM</div>
        </div>
        {/* VS badge */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-10">
          <div className="w-10 h-10 rounded-full vs-gradient flex items-center justify-center border-4 border-[#0e0e0e]">
            <span className="font-black italic text-sm text-black">VS</span>
          </div>
        </div>
      </div>
      {/* Hook */}
      <div className="px-5 py-3 text-center">
        <p className="font-medium text-base text-white leading-tight">{card.hook?.replace('⚔️ ', '')}</p>
      </div>
      {/* Why Now */}
      {card.why_now && <div className="px-5 pb-3"><WhyNowBox text={card.why_now} /></div>}
      {/* Verdict */}
      <div className="px-5 pb-4"><VerdictPill verdict={card.verdict || 'DYOR'} /></div>
      {/* Actions */}
      <ActionButtons onApe={onApe} onFade={onFade} />
    </div>
  );
}

/* ─── MacroDeskCard ─── */

export function MacroDeskCard({ card, onApe, onFade }: { card: Card; onApe: () => void; onFade: () => void }) {
  const ctx = card.institutional_context || [];
  const heroCtx = ctx[0] || { emoji: '📊', label: 'Signal', value: '—' };

  return (
    <div className="w-full max-w-sm mx-auto rounded-lg overflow-hidden select-none kinetic-glow-amber border border-[#f59e0b]/30 bg-[#131313]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[#f59e0b]/10 border-b border-[#f59e0b]/20">
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-[#f59e0b] rounded-sm">
          <span className="text-[10px] font-black text-black tracking-widest">📊 MACRO DESK</span>
        </div>
        <span className="text-[8px] font-bold text-[#f59e0b]/70 uppercase">via SoSoValue</span>
      </div>
      {/* Hero Metric */}
      <div className="py-6 flex flex-col items-center text-center bg-[#1a1919]">
        <span className="text-3xl mb-1">{heroCtx.emoji}</span>
        <div className="font-black text-4xl text-white">{heroCtx.value}</div>
        <div className="text-[10px] font-bold text-[#adaaaa] uppercase tracking-widest mt-1">{heroCtx.label}</div>
      </div>
      {/* Hook */}
      <div className="px-5 py-3 text-center">
        <p className="font-medium text-base text-white leading-tight">{card.hook}</p>
      </div>
      {/* Why Now */}
      {card.why_now && <div className="px-5 pb-3"><WhyNowBox text={card.why_now} accent="amber" /></div>}
      {/* Context chips */}
      {ctx.length > 0 && (
        <div className="px-5 pb-3 flex gap-2 flex-wrap">
          {ctx.map((c: any, i: number) => (
            <div key={i} className="bg-[#262626] px-3 py-1.5 rounded-lg flex items-center gap-1.5 border border-white/5">
              <span className="text-xs">{c.emoji}</span>
              <span className="text-[9px] text-[#adaaaa] font-bold">{c.label}:</span>
              <span className="text-[10px] text-white font-bold">{c.value}</span>
            </div>
          ))}
        </div>
      )}
      {/* Verdict */}
      <div className="px-5 pb-4"><VerdictPill verdict={card.verdict || 'DYOR'} /></div>
      {/* Actions */}
      <ActionButtons onApe={onApe} onFade={onFade} />
    </div>
  );
}

/* ─── WhaleAlertCard ─── */

export function WhaleAlertCard({ card, onApe, onFade }: { card: Card; onApe: () => void; onFade: () => void }) {
  const ctx = card.institutional_context || [];
  const entity = ctx[0] || { emoji: '🐋', label: 'Entity', value: 'Unknown' };

  return (
    <div className="w-full max-w-sm mx-auto rounded-lg overflow-hidden select-none kinetic-glow border border-[#bf81ff]/30 bg-[#131313]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[#ff7166]/10 border-b border-[#ff7166]/20">
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-gradient-to-r from-[#bf81ff] to-[#ff7166] rounded-sm">
          <span className="text-[10px] font-black text-white tracking-widest">🐋 WHALE ALERT</span>
        </div>
        <div className="w-2 h-2 rounded-full bg-[#ff7166] ape-pulse" />
      </div>
      {/* Hero */}
      <div className="py-6 flex flex-col items-center text-center bg-[#1a1919]">
        <span className="text-4xl mb-2">🐋</span>
        <div className="font-black text-3xl text-white">{entity.value}</div>
        <div className="text-[10px] font-bold text-[#adaaaa] uppercase tracking-widest mt-1">{entity.label}</div>
      </div>
      {/* Hook */}
      <div className="px-5 py-3 text-center">
        <p className="font-medium text-base text-white leading-tight">{card.hook?.replace('🐋 ', '')}</p>
      </div>
      {/* Why Now */}
      {card.why_now && <div className="px-5 pb-3"><WhyNowBox text={card.why_now} /></div>}
      {/* Context chips */}
      <div className="px-5 pb-3 flex gap-2 flex-wrap">
        {ctx.map((c: any, i: number) => (
          <div key={i} className="bg-[#262626] px-3 py-1.5 rounded-lg flex items-center gap-1.5 border border-white/5">
            <span className="text-xs">{c.emoji}</span>
            <span className="text-[9px] text-[#adaaaa] font-bold">{c.label}:</span>
            <span className="text-[10px] text-white font-bold">{c.value}</span>
          </div>
        ))}
      </div>
      {/* Verdict */}
      <div className="px-5 pb-4"><VerdictPill verdict={card.verdict || 'DYOR'} /></div>
      {/* Actions */}
      <ActionButtons onApe={onApe} onFade={onFade} />
    </div>
  );
}
