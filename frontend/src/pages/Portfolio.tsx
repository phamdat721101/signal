// import { usePrivy } from '@privy-io/react-auth';
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { config, shareToX, explorerTxUrl, normalizeAddress } from '../config';
import { useWallet } from '../hooks/useWallet';
import SodexLinks from '../components/SodexLinks';

function fmtPnl(v: number | null | undefined): string {
  if (v == null) return '--';
  return (v >= 0 ? '+' : '') + v.toFixed(2);
}
function fmtPct(v: number | null | undefined): string {
  if (v == null) return '--';
  return (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
}

// Live SoDex perps state — populated from GET /api/positions/:address.
// Shape mirrors backend `main.get_positions`. Empty when SoDex disabled.
interface SodexPosition {
  symbol: string;
  size: string;
  entry_price: string;
  unrealized_pnl_ratio?: string;
  margin_mode?: string;
}
interface SodexLiveState {
  enabled: boolean;
  account_id?: number;
  balance?: string | null;
  free_margin?: string | null;
  positions: SodexPosition[];
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

// ── Unified Positions list ──────────────────────────────────────────────
// Predict rows aggregate per-symbol (Position from aggregatePositions above).
// Summon rows render per-tx (one LP open = one row, with explorer link).
// Both share a `sortKey` (ms epoch) so a single sort gives chronological mix.
interface SummonTx {
  id: number;
  tx_hash: string;
  action: string;          // 'summon' | 'close'
  chain_id: number;
  token_symbol: string | null;
  created_at: string;
}
type PortfolioRow =
  | { kind: 'predict'; sortKey: number; data: Position }
  | { kind: 'summon';  sortKey: number; data: SummonTx };

function buildRows(positions: Position[], summons: SummonTx[]): PortfolioRow[] {
  const rows: PortfolioRow[] = [];
  for (const p of positions) rows.push({ kind: 'predict', sortKey: p.last_traded_at, data: p });
  for (const s of summons) {
    const ts = s.created_at ? Date.parse(s.created_at) : 0;
    rows.push({ kind: 'summon', sortKey: Number.isNaN(ts) ? 0 : ts, data: s });
  }
  return rows.sort((a, b) => b.sortKey - a.sortKey);
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

  const { data: lpData } = useQuery({
    queryKey: ['lp-history', address],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/lp/history/${address}`);
      if (!resp.ok) return { transactions: [] as SummonTx[] };
      return resp.json() as Promise<{ transactions: SummonTx[] }>;
    },
    enabled: !!address,
    staleTime: 30_000,
  });

  // Live SoDex perps positions — refreshes every 15s. Single Responsibility:
  // surface what the user has open right now on SoDex, keyed by address.
  const { data: sodex } = useQuery({
    queryKey: ['sodex-positions', address],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/positions/${address}`);
      if (!resp.ok) return { enabled: false, positions: [] as SodexPosition[] };
      return resp.json() as Promise<SodexLiveState>;
    },
    enabled: !!address,
    refetchInterval: 15_000,
  });

  const trades = data?.trades ?? [];
  const summary = data?.summary;
  const summons = lpData?.transactions ?? [];

  const positions = useMemo(() => aggregatePositions(trades), [trades]);
  const { best, worst } = useMemo(() => pickHeroes(trades), [trades]);
  const rows = useMemo(() => buildRows(positions, summons), [positions, summons]);

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
      {/* Live SoDex perps positions — only shown when there's something open. */}
      {sodex && sodex.enabled && sodex.positions.length > 0 && (
        <div className="bg-[#0e1a0e] border-2 border-[#8eff71]/40 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <span className="font-headline font-bold text-sm text-[#8eff71] uppercase tracking-widest">
                Live SoDex Positions
              </span>
            </div>
            {sodex.free_margin != null && (
              <span className="text-[10px] text-[#adaaaa] font-mono">
                margin {Number(sodex.free_margin).toFixed(2)} vUSDC
              </span>
            )}
          </div>
          <div className="space-y-2">
            {sodex.positions.map((p) => {
              const sz = parseFloat(p.size || '0');
              const isLong = sz >= 0;
              const pnl = parseFloat(p.unrealized_pnl_ratio || '0');
              const pnlPositive = pnl >= 0;
              return (
                <div key={p.symbol + p.entry_price} className="flex flex-col gap-2 bg-[#131313] rounded-lg p-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-headline font-bold text-white text-sm">{p.symbol}</div>
                      <div className="text-[10px] text-[#adaaaa] font-mono">
                        {isLong ? 'LONG' : 'SHORT'} {Math.abs(sz)} @ ${Number(p.entry_price).toFixed(2)}
                      </div>
                    </div>
                    <div className={`font-headline font-bold text-sm ${pnlPositive ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
                      {pnlPositive ? '+' : ''}{pnl.toFixed(2)}%
                    </div>
                  </div>
                  {/* Verify-on-SoDex link group — symbol-only, no fills toggle. */}
                  <SodexLinks symbol={p.symbol.split('-')[0]} />
                </div>
              );
            })}
          </div>
        </div>
      )}

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

      {/* Positions — unified: predicts aggregate per-symbol; summons render
          per-tx with explorer link. Sorted by most recent activity desc. */}
      <div>
        <h2 className="font-headline font-bold text-lg text-white mb-3">
          Positions {rows.length > 0 && (
            <span className="font-label text-[10px] text-[#adaaaa] ml-2">{rows.length} {rows.length === 1 ? 'entry' : 'entries'}</span>
          )}
        </h2>
        {isLoading ? (
          <div className="text-center text-[#adaaaa] text-sm py-8">Loading...</div>
        ) : rows.length === 0 ? (
          <div className="bg-[#131313] rounded-xl p-8 text-center">
            <p className="text-[#494847] text-sm">No trades yet. Start swiping!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {rows.map(r => r.kind === 'predict'
              ? <PredictRow key={`p-${r.data.symbol}`} p={r.data} />
              : <SummonRow  key={`s-${r.data.id}`}     s={r.data} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Row components (inlined — no new file). Single responsibility each. ──
function PredictRow({ p }: { p: Position }) {
  const pnlColor = p.realized_pnl_usd >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
  return (
    <div className="bg-[#131313] p-4 rounded-xl flex justify-between items-center">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-10 h-10 rounded-lg bg-[#262626] flex items-center justify-center font-headline font-bold text-[#8eff71] text-sm shrink-0">
          {p.symbol.slice(0, 2)}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-headline font-bold text-white text-sm">${p.symbol}</span>
            <span className="text-[9px] font-label uppercase tracking-widest text-[#494847]">🎯 Predict</span>
          </div>
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
}

function SummonRow({ s }: { s: SummonTx }) {
  const sym = (s.token_symbol || '?').toUpperCase();
  const isClose = s.action === 'close';
  const label = isClose ? 'Banish' : 'Summon';
  const icon = isClose ? '🔥' : '🔮';
  return (
    <a
      href={explorerTxUrl(s.tx_hash, s.chain_id)}
      target="_blank"
      rel="noopener noreferrer"
      className="bg-[#131313] p-4 rounded-xl flex justify-between items-center hover:bg-[#191919] transition-colors"
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-10 h-10 rounded-lg bg-[#bf81ff]/10 flex items-center justify-center text-base shrink-0">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-headline font-bold text-white text-sm">${sym}</span>
            <span className="text-[9px] font-label uppercase tracking-widest text-[#bf81ff]">🔮 LP {label}</span>
          </div>
          <div className="font-label text-[10px] text-[#adaaaa]">
            Open liquidity position · {new Date(s.created_at).toLocaleDateString()}
          </div>
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="font-label text-[11px] text-[#bf81ff]">{s.tx_hash.slice(0, 10)}… ↗</div>
      </div>
    </a>
  );
}
