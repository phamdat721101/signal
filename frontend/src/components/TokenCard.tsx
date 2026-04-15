import type { Card } from '../hooks/useCards';

function fmt(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(2)}`;
}

export default function TokenCard({ card, onApe, onFade }: {
  card: Card;
  onApe: () => void;
  onFade: () => void;
}) {
  const pctColor = card.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
  const pctSign = card.price_change_24h >= 0 ? '+' : '';

  return (
    <div className="relative w-full h-full max-w-md bg-[#131313] rounded-xl overflow-hidden flex flex-col border border-[#494847]/10">
      {/* Image area */}
      <div className="relative flex-grow min-h-0 overflow-hidden">
        {card.image_url ? (
          <img src={card.image_url} alt={card.token_name} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-[#131313] via-[#1a1919] to-[#262626] flex items-center justify-center">
            <span className="font-headline font-black text-8xl text-[#262626]">${card.token_symbol}</span>
          </div>
        )}

        {/* Chain badge */}
        <div className="absolute top-4 left-4 glass-effect px-3 py-1 rounded-full border border-[#8eff71]/20 flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[#8eff71] kinetic-pulse" />
          <span className="font-label text-[10px] font-bold text-[#8eff71] tracking-widest uppercase">{card.chain}</span>
        </div>

        {/* Token + price */}
        <div className="absolute top-4 right-4 text-right">
          <div className="font-headline font-bold text-2xl text-white leading-none">${card.token_symbol}</div>
          <div className={`font-label text-xs mt-1 tracking-wider uppercase ${pctColor}`}>
            {card.price >= 1 ? `$${card.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `$${card.price.toFixed(6)}`}
          </div>
        </div>

        {/* Ghost overlays */}
        <div className="absolute inset-0 pointer-events-none flex justify-between items-center px-6">
          <div className="opacity-[0.06] rotate-[-12deg] border-4 border-[#ff7166] p-4 rounded-xl">
            <span className="font-headline font-black text-5xl text-[#ff7166]">FADE</span>
          </div>
          <div className="opacity-[0.06] rotate-[12deg] border-4 border-[#8eff71] p-4 rounded-xl">
            <span className="font-headline font-black text-5xl text-[#8eff71]">APE</span>
          </div>
        </div>

        {/* Gradient overlay */}
        <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-[#0e0e0e] via-[#0e0e0e]/40 to-transparent" />
      </div>

      {/* Content overlay */}
      <div className="absolute bottom-0 w-full p-5 space-y-3">
        {/* Hook + roast */}
        <p className="text-[#adaaaa] font-medium text-sm leading-snug">{card.hook} {card.roast}</p>

        {/* Metrics bento grid */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-[#262626] p-3 rounded-lg">
            <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">24H Change</div>
            <div className={`font-headline font-bold text-lg ${pctColor}`}>{pctSign}{card.price_change_24h.toFixed(1)}%</div>
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

        {/* Action buttons */}
        <div className="flex gap-3 pt-1">
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
    </div>
  );
}
