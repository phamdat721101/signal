import { useInterwovenKit } from '@initia/interwovenkit-react';
import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

export default function Portfolio() {
  const { initiaAddress } = useInterwovenKit();

  const { data } = useQuery({
    queryKey: ['userSwipes', initiaAddress],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/cards/user/${initiaAddress}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ swipes: any[]; total: number }>;
    },
    enabled: !!initiaAddress,
  });

  const swipes = data?.swipes ?? [];
  const apes = swipes.filter((s) => s.action === 'ape');
  const totalTrades = swipes.length;
  const winRate = apes.length > 0 ? Math.round((apes.filter((a) => (a.price_change_24h ?? 0) > 0).length / apes.length) * 100) : 0;

  if (!initiaAddress) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
        <span className="material-symbols-outlined text-6xl text-[#494847]">account_balance_wallet</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Connect wallet to view portfolio</p>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-5">
      {/* Balance header */}
      <div className="text-center py-6">
        <div className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest mb-2">Total Trades</div>
        <div className="font-headline text-5xl font-black text-[#8eff71]">{totalTrades}</div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-[#262626] p-4 rounded-xl">
          <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Apes</div>
          <div className="font-headline text-2xl font-bold text-[#8eff71]">{apes.length}</div>
        </div>
        <div className="bg-[#262626] p-4 rounded-xl">
          <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Fades</div>
          <div className="font-headline text-2xl font-bold text-[#ff7166]">{totalTrades - apes.length}</div>
        </div>
        <div className="bg-[#262626] p-4 rounded-xl">
          <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Win Rate</div>
          <div className="font-headline text-2xl font-bold text-white">{winRate}%</div>
        </div>
      </div>

      {/* Active positions */}
      <div>
        <h2 className="font-headline font-bold text-lg text-white mb-3">Active Positions</h2>
        {apes.length === 0 ? (
          <div className="bg-[#131313] rounded-xl p-8 text-center">
            <p className="text-[#494847] text-sm">No apes yet. Start swiping!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {apes.map((s: any) => (
              <div key={s.id} className="bg-[#131313] p-4 rounded-xl flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-[#262626] flex items-center justify-center font-headline font-bold text-[#8eff71] text-sm">
                    {s.token_symbol?.slice(0, 2)}
                  </div>
                  <div>
                    <div className="font-headline font-bold text-white text-sm">${s.token_symbol}</div>
                    <div className="font-label text-[10px] text-[#adaaaa]">{s.token_name}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`font-headline font-bold text-sm kinetic-pulse ${(s.price_change_24h ?? 0) >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
                    {(s.price_change_24h ?? 0) >= 0 ? '+' : ''}{(s.price_change_24h ?? 0).toFixed(1)}%
                  </div>
                  <div className="font-label text-[10px] text-[#adaaaa]">
                    ${s.price >= 1 ? s.price?.toLocaleString(undefined, { maximumFractionDigits: 2 }) : s.price?.toFixed(6)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
