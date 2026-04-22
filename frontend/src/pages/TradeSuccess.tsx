import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { config, shareToX } from '../config';
import type { Card } from '../hooks/useCards';

export default function TradeSuccess() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const trade = (location.state as any)?.trade;

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
      <div className="absolute top-1/4 left-1/4 w-64 h-64 bg-[#8eff71]/5 rounded-full blur-[120px]" />
      <div className="absolute bottom-1/4 right-1/4 w-64 h-64 bg-[#bf81ff]/5 rounded-full blur-[120px]" />

      <div className="relative z-10 flex flex-col items-center text-center space-y-6 w-full max-w-md">
        <div className="relative">
          <div className="absolute inset-0 bg-[#8eff71]/20 blur-3xl rounded-full scale-150" />
          <div className="relative w-32 h-32 flex items-center justify-center bg-[#262626]/40 backdrop-blur-xl border border-[#8eff71]/20 rounded-full">
            <span className="material-symbols-outlined text-6xl text-[#8eff71]" style={{ fontVariationSettings: "'FILL' 1" }}>rocket_launch</span>
          </div>
        </div>

        <div>
          <h1 className="font-headline text-2xl font-black text-[#8eff71] italic uppercase">TRADE EXECUTED</h1>
          <p className="font-label text-[#adaaaa] text-xs uppercase tracking-widest mt-1">
            Aped into ${card?.token_symbol ?? '...'}
          </p>
        </div>

        {/* Trade details */}
        {trade && (
          <div className="w-full space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-[#262626] p-4 rounded-xl">
                <span className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">Entry Price</span>
                <div className="font-headline text-lg font-bold text-white mt-1">
                  ${trade.entry_price >= 1 ? trade.entry_price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : trade.entry_price.toFixed(6)}
                </div>
              </div>
              <div className="bg-[#262626] p-4 rounded-xl">
                <span className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">Amount</span>
                <div className="font-headline text-lg font-bold text-[#8eff71] mt-1">${trade.amount_usd.toFixed(2)}</div>
                <div className="font-label text-[10px] text-[#adaaaa]">{trade.token_amount} {card?.token_symbol}</div>
              </div>
            </div>

            {/* Tx hash */}
            {trade.tx_hash && (
              <div className="w-full bg-[#131313] p-4 rounded-xl border border-[#494847]/10">
                <div className="font-label text-[9px] text-[#bf81ff] uppercase tracking-widest mb-1">
                  {trade.on_chain ? 'On-Chain Transaction' : 'Simulated Trade ID'}
                </div>
                <div className="font-mono text-xs text-[#adaaaa] truncate">{trade.tx_hash}</div>
                {trade.explorer_url ? (
                  <a href={trade.explorer_url} target="_blank" rel="noopener noreferrer"
                    className="font-label text-[10px] text-[#8eff71] mt-1 flex items-center gap-1 hover:underline">
                    View in Explorer <span className="material-symbols-outlined text-[12px]">open_in_new</span>
                  </a>
                ) : (
                  <div className="font-label text-[10px] text-[#494847] mt-1">Paper trade — no on-chain record</div>
                )}
              </div>
            )}
          </div>
        )}

        <button onClick={() => navigate('/portfolio')}
          className="w-full ape-gradient text-[#0b5800] font-headline font-black py-4 rounded-lg tracking-widest uppercase active:scale-95 transition-transform flex items-center justify-center gap-3">
          GO TO PORTFOLIO
          <span className="material-symbols-outlined text-lg">arrow_forward</span>
        </button>

        {trade && (
          <button onClick={() => shareToX(
            `I just aped $${card?.token_symbol} at $${trade.entry_price >= 1 ? trade.entry_price.toLocaleString(undefined, {maximumFractionDigits: 2}) : trade.entry_price.toFixed(6)} on @KineticApp 🚀 My alpha has receipts. #ApeOrFade`,
            trade.explorer_url || undefined
          )} className="w-full bg-[#262626] text-[#adaaaa] font-headline font-bold py-3 rounded-lg flex items-center justify-center gap-2 mt-2">
            <span className="material-symbols-outlined text-lg">share</span>
            Share to X
          </button>
        )}
      </div>
    </div>
  );
}
