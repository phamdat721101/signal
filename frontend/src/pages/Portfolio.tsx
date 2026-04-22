import { usePrivy } from '@privy-io/react-auth';
import { useQuery } from '@tanstack/react-query';
import { config, shareToX } from '../config';

function fmtPnl(v: number | null): string {
  if (v == null) return '--';
  return (v >= 0 ? '+' : '') + v.toFixed(2);
}

export default function Portfolio() {
  const { user } = usePrivy();
  const address = user?.wallet?.address || '';

  const { data, isLoading } = useQuery({
    queryKey: ['trades', address],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/trades/${address}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ trades: any[]; total: number; summary: any }>;
    },
    enabled: !!address,
  });

  const trades = data?.trades ?? [];
  const summary = data?.summary;

  if (!address) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
        <span className="material-symbols-outlined text-6xl text-[#494847]">account_balance_wallet</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Connect wallet to view portfolio</p>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-5">
      {/* Summary */}
      {summary && (
        <div className="text-center py-4">
          <div className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest mb-2">Total PnL</div>
          <div className={"font-headline text-4xl font-black " + ((summary.total_pnl_usd || 0) >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]')}>
            {fmtPnl(summary.total_pnl_usd)}
            <span className="text-lg ml-1">USD</span>
          </div>
        </div>
      )}

      {/* Stats grid */}
      {summary && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-[#262626] p-4 rounded-xl">
            <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Trades</div>
            <div className="font-headline text-2xl font-bold text-white">{summary.total_trades}</div>
          </div>
          <div className="bg-[#262626] p-4 rounded-xl">
            <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Wins</div>
            <div className="font-headline text-2xl font-bold text-[#8eff71]">{summary.win_count}</div>
          </div>
          <div className="bg-[#262626] p-4 rounded-xl">
            <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1">Invested</div>
            <div className="font-headline text-xl font-bold text-white">${summary.total_invested?.toFixed(0)}</div>
          </div>
        </div>
      )}

      {/* VIP Badge */}
        <div className="bg-[#bf81ff]/10 border border-[#bf81ff]/20 p-4 rounded-xl flex items-center gap-3">
          <span className="material-symbols-outlined text-[#bf81ff]" style={{ fontVariationSettings: "'FILL' 1" }}>stars</span>
          <div>
            <div className="font-headline font-bold text-sm text-[#bf81ff]">VIP Rewards Coming</div>
            <div className="font-label text-[10px] text-[#adaaaa]">Earn esINIT for every swipe via Initia VIP gauge</div>
          </div>
        </div>

      {/* Positions */}
      <div>
        <h2 className="font-headline font-bold text-lg text-white mb-3">Positions</h2>
        {isLoading ? (
          <div className="text-center text-[#adaaaa] text-sm py-8">Loading...</div>
        ) : trades.length === 0 ? (
          <div className="bg-[#131313] rounded-xl p-8 text-center">
            <p className="text-[#494847] text-sm">No trades yet. Start swiping!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {trades.map((t: any) => {
              const pnl = t.pnl_usd ?? 0;
              const pnlColor = pnl >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
              return (
                <div key={t.id} className="bg-[#131313] p-4 rounded-xl flex justify-between items-center">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-[#262626] flex items-center justify-center font-headline font-bold text-[#8eff71] text-sm">
                      {t.token_symbol?.slice(0, 2)}
                    </div>
                    <div>
                      <div className="font-headline font-bold text-white text-sm">${t.token_symbol}</div>
                      <div className="font-label text-[10px] text-[#adaaaa]">{t.token_amount?.toFixed(4)} tokens</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className={"font-headline font-bold text-sm " + pnlColor}>{fmtPnl(pnl)} USD</div>
                    <div className={"font-label text-[10px] " + pnlColor}>{fmtPnl(t.pnl_pct)}%</div>
                    {t.resolved && <div className="flex items-center gap-1">
                      <span className="font-label text-[8px] text-[#494847]">CLOSED</span>
                      <button onClick={() => shareToX((t.pnl_usd || 0) > 0
                        ? `Called $${t.token_symbol}. +${(t.pnl_pct || 0).toFixed(1)}% 🧠 @KineticApp #ApeOrFade`
                        : `Aped $${t.token_symbol}. ${(t.pnl_pct || 0).toFixed(1)}%. Pain. 😭 @KineticApp`
                      )}><span className="material-symbols-outlined text-[12px] text-[#494847]">share</span></button>
                    </div>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
