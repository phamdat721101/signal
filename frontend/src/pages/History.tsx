import { useInterwovenKit } from '@initia/interwovenkit-react';
import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

export default function History() {
  const { initiaAddress } = useInterwovenKit();

  const { data, isLoading } = useQuery({
    queryKey: ['history', initiaAddress],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/cards/user/${initiaAddress}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ swipes: any[]; total: number }>;
    },
    enabled: !!initiaAddress,
  });

  const swipes = data?.swipes ?? [];

  if (!initiaAddress) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
        <span className="material-symbols-outlined text-6xl text-[#494847]">receipt_long</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Connect wallet to view history</p>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="font-headline text-xl font-bold text-white">Terminal History</h1>
        <span className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">{swipes.length} swipes</span>
      </div>

      {isLoading ? (
        <div className="text-center text-[#adaaaa] font-label text-sm py-12">Loading...</div>
      ) : swipes.length === 0 ? (
        <div className="bg-[#131313] rounded-xl p-12 text-center">
          <span className="material-symbols-outlined text-5xl text-[#494847] mb-3">swipe</span>
          <p className="text-[#494847] text-sm">No swipes yet. Hit the feed.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {swipes.map((s: any) => {
            const isApe = s.action === 'ape';
            const ts = s.created_at ? new Date(s.created_at).toLocaleDateString() : '';
            return (
              <div key={s.id} className="bg-[#131313] p-4 rounded-xl flex items-center gap-3">
                {/* Action icon */}
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                  isApe ? 'bg-[#8eff71]/10' : 'bg-[#ff7166]/10'
                }`}>
                  <span className={`material-symbols-outlined text-lg ${isApe ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}
                    style={isApe ? { fontVariationSettings: "'FILL' 1" } : undefined}>
                    {isApe ? 'bolt' : 'close'}
                  </span>
                </div>

                {/* Token info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-headline font-bold text-white text-sm">${s.token_symbol}</span>
                    <span className={`text-[9px] font-label font-bold px-2 py-0.5 rounded ${
                      isApe ? 'bg-[#8eff71]/10 text-[#8eff71]' : 'bg-[#ff7166]/10 text-[#ff7166]'
                    }`}>
                      {isApe ? 'APE' : 'FADE'}
                    </span>
                  </div>
                  <div className="font-label text-[10px] text-[#adaaaa] mt-0.5">{s.hook || s.token_name}</div>
                </div>

                {/* Price + date */}
                <div className="text-right shrink-0">
                  {isApe && s.price_change_24h != null && (
                    <div className={`font-headline font-bold text-sm ${s.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
                      {s.price_change_24h >= 0 ? '+' : ''}{s.price_change_24h.toFixed(1)}%
                    </div>
                  )}
                  <div className="font-label text-[10px] text-[#adaaaa]">{ts}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
