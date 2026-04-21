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

const verdictColor: Record<string, string> = {
  APE: 'bg-[#8eff71]/15 text-[#8eff71] border-[#8eff71]/30',
  FADE: 'bg-[#ff7166]/15 text-[#ff7166] border-[#ff7166]/30',
  DYOR: 'bg-[#bf81ff]/15 text-[#bf81ff] border-[#bf81ff]/30',
};

export default function TokenCard({ card, onApe, onFade }: {
  card: Card;
  onApe: () => void;
  onFade: () => void;
}) {
  const pctColor = card.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
  const pctSign = card.price_change_24h >= 0 ? '+' : '';
  const [imgError, setImgError] = useState(false);
  const verdict = card.verdict || 'DYOR';

  return (
    <div className="w-full max-w-md mx-auto bg-[#131313] rounded-xl overflow-hidden flex flex-col border border-[#494847]/10">
      {/* Header: token info + price */}
      <div className="flex items-center justify-between p-4 pb-2">
        <div className="flex items-center gap-3">
          {/* Token logo */}
          <div className="w-10 h-10 rounded-full bg-[#262626] overflow-hidden flex-shrink-0">
            {card.image_url && !imgError ? (
              <img src={card.image_url} alt={card.token_symbol} className="w-full h-full object-cover" onError={() => setImgError(true)} />
            ) : (
              <div className="w-full h-full flex items-center justify-center font-headline font-bold text-sm text-[#adaaaa]">{card.token_symbol.slice(0, 2)}</div>
            )}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-headline font-bold text-lg text-white">${card.token_symbol}</span>
              <span className={`text-[9px] font-label font-bold px-2 py-0.5 rounded border ${verdictColor[verdict] || verdictColor.DYOR}`}>{verdict}</span>
            </div>
            <div className="font-label text-xs text-[#adaaaa]">{card.token_name}</div>
          </div>
        </div>
        <div className="text-right">
          <div className="font-headline font-bold text-white">{fmtPrice(card.price)}</div>
          <div className={`font-label text-xs ${pctColor}`}>{pctSign}{card.price_change_24h.toFixed(1)}%</div>
        </div>
      </div>

      {/* Hook + roast */}
      <div className="px-4 py-2">
        <p className="text-[#adaaaa] text-sm leading-relaxed">{card.hook}</p>
        {card.roast && <p className="text-[#494847] text-xs mt-1">{card.roast}</p>}
      </div>

      {/* Metrics bento grid */}
      <div className="px-4 pb-2">
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-[#262626] p-3 rounded-lg">
            <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Market Cap</div>
            <div className="font-headline font-bold text-sm text-white">{fmt(card.market_cap)}</div>
          </div>
          <div className="bg-[#262626] p-3 rounded-lg">
            <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Volume 24H</div>
            <div className="font-headline font-bold text-sm text-white">{fmt(card.volume_24h)}</div>
          </div>
          {card.metrics.length > 0 && (
            <div className="col-span-2 bg-[#bf81ff]/10 p-3 rounded-lg border border-[#bf81ff]/20 flex justify-between items-center">
              <div>
                <div className="font-label text-[9px] text-[#bf81ff] uppercase tracking-widest">AI Insight</div>
                <div className="font-headline font-bold text-sm text-white">
                  {typeof card.metrics[0] === 'string' ? card.metrics[0] : `${card.metrics[0].emoji} ${card.metrics[0].value}`}
                </div>
              </div>
              <span className="material-symbols-outlined text-[#bf81ff]" style={{ fontVariationSettings: "'FILL' 1" }}>monitoring</span>
            </div>
          )}
        </div>
      </div>

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
