// import { usePrivy } from '@privy-io/react-auth';
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { config, shareToX, normalizeAddress } from '../config';
import { useWallet } from '../hooks/useWallet';

function fmtPnl(v: number | null | undefined): string {
  if (v == null) return '--';
  return (v >= 0 ? '+' : '') + v.toFixed(2);
}
function fmtPct(v: number | null | undefined): string {
  if (v == null) return '--';
  return (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
}

// ── Position aggregation (pure derive — single responsibility, inlined) ──
interface Trade {
  id: number;
  token_symbol: string;
  token_amount: number;
  amount_usd?: number;
  pnl_usd?: number | null;
  pnl_pct?: number | null;
  resolved?: boolean;
  created_at?: string;
}
interface Position {
  symbol: string;
  total_amount: number;
  invested_usd: number;
  realized_pnl_usd: number;     // sum of pnl_usd from resolved trades only
  best_pct: number | null;
  worst_pct: number | null;
  trade_count: number;
  resolved_count: number;
  pending_count: number;
  last_traded_at: number;       // ms epoch — for sort stability
}

function aggregatePositions(trades: Trade[]): Position[] {
  const map = new Map<string, Position>();
  for (const t of trades) {
    const sym = (t.token_symbol || '').toUpperCase();
    if (!sym) continue;
    const existing = map.get(sym) || {
      symbol: sym, total_amount: 0, invested_usd: 0, realized_pnl_usd: 0,
      best_pct: null, worst_pct: null, trade_count: 0, resolved_count: 0,
      pending_count: 0, last_traded_at: 0,
    };
    existing.total_amount  += Number(t.token_amount || 0);
    existing.invested_usd  += Number(t.amount_usd  || 0);
    existing.trade_count   += 1;
    if (t.resolved) {
      existing.resolved_count += 1;
      existing.realized_pnl_usd += Number(t.pnl_usd || 0);
      const pct = Number(t.pnl_pct);
      if (!Number.isNaN(pct)) {
        if (existing.best_pct  === null || pct > existing.best_pct)  existing.best_pct  = pct;
        if (existing.worst_pct === null || pct < existing.worst_pct) existing.worst_pct = pct;
      }
    } else {
      existing.pending_count += 1;
    }
    const ts = t.created_at ? Date.parse(t.created_at) : 0;
    if (ts > existing.last_traded_at) existing.last_traded_at = ts;
    map.set(sym, existing);
  }
  return Array.from(map.values()).sort((a, b) => b.last_traded_at - a.last_traded_at);
}

interface HeroCall {
  symbol: string;
  pnl_pct: number;
  pnl_usd: number;
  resolved: boolean;
}
function pickHeroes(trades: Trade[]): { best: HeroCall | null; worst: HeroCall | null } {
  let best: HeroCall | null = null;
  let worst: HeroCall | null = null;
  for (const t of trades) {
    if (!t.resolved || t.pnl_pct == null) continue;
    const c: HeroCall = {
      symbol: (t.token_symbol || '').toUpperCase(),
      pnl_pct: Number(t.pnl_pct),
      pnl_usd: Number(t.pnl_usd || 0),
      resolved: true,
    };
    if (best === null  || c.pnl_pct > best.pnl_pct)  best  = c;
    if (worst === null || c.pnl_pct < worst.pnl_pct) worst = c;
  }
  return { best, worst };
}

export default function Portfolio() {
  const { address: walletAddr } = useWallet();
  const address = normalizeAddress(walletAddr);

  const { data, isLoading } = useQuery({
    queryKey: ['trades', address],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/trades/${address}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ trades: Trade[]; total: number; summary: any }>;
    },
    enabled: !!address,
  });

  const trades = data?.trades ?? [];
  const summary = data?.summary;

  const positions = useMemo(() => aggregatePositions(trades), [trades]);
  const { best, worst } = useMemo(() => pickHeroes(trades), [trades]);

  if (!address) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
        <span className="material-symbols-outlined text-6xl text-[#494847]">account_balance_wallet</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Connect wallet to view portfolio</p>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-5 pb-24">
      {/* Summary header */}
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

      {/* Best / Worst hero — story, not spreadsheet */}
      {(best || worst) && (
        <div className="grid grid-cols-2 gap-3">
          {best ? (
            <div className="bg-[#131313] border border-[#8eff71]/20 p-3 rounded-xl">
              <div className="font-label text-[9px] text-[#8eff71] uppercase tracking-widest mb-1">🚀 Best Call</div>
              <div className="font-headline text-lg font-bold text-white">${best.symbol}</div>
              <div className="font-headline font-bold text-[#8eff71] text-base">{fmtPct(best.pnl_pct)}</div>
              <div className="font-label text-[10px] text-[#adaaaa]">{fmtPnl(best.pnl_usd)} USD</div>
              <button onClick={() => shareToX(`Called $${best.symbol}. ${fmtPct(best.pnl_pct)} on @KineticApp 🧠 #ApeOrFade`)}
                className="mt-1 text-[10px] text-[#494847] flex items-center gap-1 hover:text-[#8eff71]">
                <span className="material-symbols-outlined text-[12px]">share</span>Share
              </button>
            </div>
          ) : <div className="bg-[#131313] border border-[#494847]/20 p-3 rounded-xl opacity-50">
            <div className="font-label text-[9px] text-[#494847] uppercase tracking-widest mb-1">🚀 Best Call</div>
            <div className="font-label text-[10px] text-[#494847]">No resolved wins yet</div>
          </div>}
          {worst ? (
            <div className="bg-[#131313] border border-[#ff7166]/20 p-3 rounded-xl">
              <div className="font-label text-[9px] text-[#ff7166] uppercase tracking-widest mb-1">💀 Worst Call</div>
              <div className="font-headline text-lg font-bold text-white">${worst.symbol}</div>
              <div className="font-headline font-bold text-[#ff7166] text-base">{fmtPct(worst.pnl_pct)}</div>
              <div className="font-label text-[10px] text-[#adaaaa]">{fmtPnl(worst.pnl_usd)} USD</div>
              <div className="mt-1 text-[10px] text-[#494847] italic">tuition paid 📚</div>
            </div>
          ) : <div className="bg-[#131313] border border-[#494847]/20 p-3 rounded-xl opacity-50">
            <div className="font-label text-[9px] text-[#494847] uppercase tracking-widest mb-1">💀 Worst Call</div>
            <div className="font-label text-[10px] text-[#494847]">No resolved losses</div>
          </div>}
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

      {/* Positions — aggregated by token (no more duplicates) */}
      <div>
        <h2 className="font-headline font-bold text-lg text-white mb-3">
          Positions {positions.length > 0 && (
            <span className="font-label text-[10px] text-[#adaaaa] ml-2">{positions.length} unique</span>
          )}
        </h2>
        {isLoading ? (
          <div className="text-center text-[#adaaaa] text-sm py-8">Loading...</div>
        ) : positions.length === 0 ? (
          <div className="bg-[#131313] rounded-xl p-8 text-center">
            <p className="text-[#494847] text-sm">No trades yet. Start swiping!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {positions.map((p) => {
              const pnlColor = p.realized_pnl_usd >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
              return (
                <div key={p.symbol} className="bg-[#131313] p-4 rounded-xl flex justify-between items-center">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-lg bg-[#262626] flex items-center justify-center font-headline font-bold text-[#8eff71] text-sm shrink-0">
                      {p.symbol.slice(0, 2)}
                    </div>
                    <div className="min-w-0">
                      <div className="font-headline font-bold text-white text-sm">${p.symbol}</div>
                      <div className="font-label text-[10px] text-[#adaaaa]">
                        {p.total_amount.toFixed(4)} tokens · {p.trade_count} swipe{p.trade_count > 1 ? 's' : ''}
                        {p.pending_count > 0 && (
                          <span className="ml-1 text-[#bf81ff]">· {p.pending_count} pending</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    {p.resolved_count > 0 ? (
                      <>
                        <div className={"font-headline font-bold text-sm " + pnlColor}>
                          {fmtPnl(p.realized_pnl_usd)} USD
                        </div>
                        <div className="font-label text-[10px] text-[#adaaaa]">
                          best {fmtPct(p.best_pct)} · worst {fmtPct(p.worst_pct)}
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="font-label text-[11px] text-[#bf81ff]">⏳ Pending</div>
                        <div className="font-label text-[10px] text-[#adaaaa]">${p.invested_usd.toFixed(2)} invested</div>
                      </>
                    )}
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
