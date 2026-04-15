import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { config } from '../config';
import type { Card } from '../hooks/useCards';

export default function TradeSuccess() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: card } = useQuery<Card>({
    queryKey: ['card', id],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/cards/${id}`);
      if (!resp.ok) throw new Error('Card not found');
      return resp.json();
    },
    enabled: !!id,
  });

  return (
    <div className="flex flex-col items-center justify-center h-full px-6 relative overflow-hidden">
      {/* Ambient blurs */}
      <div className="absolute top-1/4 left-1/4 w-64 h-64 bg-[#8eff71]/5 rounded-full blur-[120px]" />
      <div className="absolute bottom-1/4 right-1/4 w-64 h-64 bg-[#bf81ff]/5 rounded-full blur-[120px]" />

      <div className="relative z-10 flex flex-col items-center text-center space-y-6 w-full max-w-md">
        {/* Rocket icon with HUD rings */}
        <div className="relative">
          <div className="absolute inset-0 bg-[#8eff71]/20 blur-3xl rounded-full scale-150" />
          <div className="relative w-40 h-40 flex items-center justify-center bg-[#262626]/40 backdrop-blur-xl border border-[#8eff71]/20 rounded-full">
            <span className="material-symbols-outlined text-7xl text-[#8eff71]"
              style={{ fontVariationSettings: "'FILL' 1" }}>rocket_launch</span>
            <div className="absolute inset-[-10px] border-2 border-dashed border-[#8eff71]/10 rounded-full animate-[spin_20s_linear_infinite]" />
            <div className="absolute inset-[-20px] border border-[#bf81ff]/20 rounded-full animate-[spin_30s_linear_infinite_reverse]" />
          </div>
        </div>

        <div>
          <h1 className="font-headline text-3xl font-black tracking-tight text-[#8eff71] italic uppercase">
            TRADE SUCCESSFUL! 🚀
          </h1>
          <p className="font-label text-[#adaaaa] tracking-widest text-xs uppercase mt-1">
            Aping into ${card?.token_symbol ?? '...'}
          </p>
        </div>

        {/* ZK progress bar */}
        <div className="w-full bg-[#131313] p-4 rounded-lg border border-[#494847]/10 space-y-3">
          <div className="flex justify-between items-end">
            <div className="flex flex-col text-left">
              <span className="text-[#bf81ff] font-headline font-bold text-[10px] tracking-widest uppercase flex items-center gap-1">
                <span className="material-symbols-outlined text-[12px]">security</span> ZK-AI PRIVACY LAYER
              </span>
              <span className="font-label text-sm text-white mt-1">Verifying on Initia...</span>
            </div>
            <span className="font-label text-[#8eff71] text-xs">100%</span>
          </div>
          <div className="w-full h-1 bg-[#262626] overflow-hidden">
            <div className="w-full h-full bg-gradient-to-r from-[#8eff71] to-[#2ff801]" />
          </div>
          <div className="flex justify-between text-[10px] font-label text-[#adaaaa]">
            <span>SIGNAL RECORDED ON-CHAIN</span>
            <span className="text-[#8eff71]">DONE</span>
          </div>
        </div>

        {/* P&L bento */}
        {card && (
          <div className="w-full grid grid-cols-2 gap-3">
            <div className="bg-[#262626] p-4 rounded-xl flex flex-col items-start">
              <span className="font-label text-[10px] text-[#adaaaa] tracking-widest uppercase mb-1">Entry Price</span>
              <span className="font-headline text-xl font-bold text-white">
                ${card.price >= 1 ? card.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : card.price.toFixed(6)}
              </span>
            </div>
            <div className="bg-[#262626] p-4 rounded-xl flex flex-col items-start">
              <span className="font-label text-[10px] text-[#adaaaa] tracking-widest uppercase mb-1">24H Change</span>
              <span className={`font-headline text-xl font-bold kinetic-pulse ${card.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
                {card.price_change_24h >= 0 ? '+' : ''}{card.price_change_24h.toFixed(2)}%
              </span>
            </div>
          </div>
        )}

        {/* CTA */}
        <button onClick={() => navigate('/portfolio')}
          className="w-full ape-gradient text-[#0b5800] font-headline font-black py-4 rounded-lg tracking-widest uppercase shadow-[0_0_24px_rgba(142,255,113,0.3)] active:scale-95 transition-transform flex items-center justify-center gap-3">
          GO TO PORTFOLIO
          <span className="material-symbols-outlined text-lg">arrow_forward</span>
        </button>
      </div>
    </div>
  );
}
